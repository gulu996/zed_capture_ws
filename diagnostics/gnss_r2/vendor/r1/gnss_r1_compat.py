#!/usr/bin/env python3
"""Offline only: byte-preserving compatibility audit of the observed Unicore ASCII formats."""
import binascii
import dataclasses
import datetime as dt
import importlib.util
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
LEGACY_PATH = ROOT / 'inputs/jetson/catkin_ws/src/gnss_serial_driver/src/gnss_serial_driver/parser.py'
spec = importlib.util.spec_from_file_location('archived_gnss_parser', LEGACY_PATH)
legacy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = legacy
spec.loader.exec_module(legacy)
NS = 1_000_000_000
DAY = 86400 * NS
EPOCH = dt.date(1970, 1, 1)
GPS_EPOCH_NS = (dt.date(1980, 1, 6) - EPOCH).days * DAY


def crc32_unicore(body):
    # stdlib CRC has complemented initial/final state; Unicore uses 0 / no final xor.
    return binascii.crc32(body, 0xffffffff) ^ 0xffffffff


def checksum(raw):
    payload = raw.rstrip(b'\r\n')
    if payload.startswith(b'#'):
        match = re.fullmatch(rb'#([^\r\n]*)\*([0-9a-fA-F]{8})', payload)
        computed = crc32_unicore(match[1]) if match else None
    elif payload.startswith(b'$'):
        match = re.fullmatch(rb'\$([^*\r\n]*)\*([0-9a-fA-F]{2})', payload)
        computed = 0 if match else None
        if match:
            for byte in match[1]:
                computed ^= byte
    else:
        match, computed = None, None
    received = int(match[2], 16) if match else None
    return {'checksum_valid': match is not None and received == computed,
            'checksum_received': received, 'checksum_computed': computed,
            'checksum_reason': 'PASS' if match and received == computed else
            ('CHECKSUM_MISMATCH' if match else 'MISSING_OR_MALFORMED_CHECKSUM')}


def split_record(raw):
    """Return a complete partition, never reconstruct bytes or split a valid parent."""
    if checksum(raw)['checksum_valid']:
        return [(raw, 'NONE')]
    # ponytail: only recover the observed numeric AGRICA -> complete RMC fault.
    # Other ambiguous concatenations stay raw; extend only with real protocol evidence.
    if raw.startswith(b'#AGRICA,') and b';GNSS,' in raw and b'"' not in raw:
        for m in re.finditer(rb'\$G[PN]RMC,', raw):
            prefix, tail = raw[:m.start()], raw[m.start():]
            numeric = prefix.split(b';GNSS,', 1)[1]
            if re.fullmatch(rb'[0-9eE+.,-]+', numeric) and b'*' not in prefix and \
                    checksum(tail)['checksum_valid'] and len(tail.split(b',')) >= 13:
                return [(prefix, 'TRUNCATED_AGRICA_BEFORE_VALID_RMC'),
                        (tail, 'RESYNC_AFTER_TRUNCATED_AGRICA')]
    return [(raw, 'NONE')]


def frames(raw, chunks=(), recorded_lines=()):
    """Partition source bytes including delimiters, link original read chunks/line IDs."""
    line_by_start = {x['byte_begin']: x['line_id'] for x in recorded_lines}
    offset, record_sequence = 0, 0
    # CR/LF only, not bytes.splitlines()'s additional control-character boundaries.
    for match in re.finditer(rb'[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z', raw):
        assert match.start() == offset
        line_start = offset
        for part, recovery in split_record(match[0]):
            record_sequence += 1
            end = offset + len(part)
            overlaps = [c for c in chunks if c['byte_offset'] < end and
                        c['byte_offset'] + c['byte_count'] > offset]
            yield {'record_sequence': record_sequence, 'source_sequence': line_by_start.get(line_start),
                   'source_sequence_origin': 'recorded line_id; ROS source_sequence not recorded',
                   'byte_begin': offset, 'byte_end': end, 'raw_hex': part.hex(),
                   'chunk_ids': [c['chunk_id'] for c in overlaps],
                   'receive_clocks': overlaps[-1]['receive_clocks'] if overlaps else None,
                   'recovery_reason': recovery}
            offset = end
    assert offset == len(raw)


def utc_ns(day, clock):
    match = re.fullmatch(r'(\d{2})(\d{2})(\d{2})(?:\.(\d{1,9}))?', clock)
    if not match:
        raise ValueError('INVALID_TIME_TEXT_OR_PRECISION')
    hour, minute, second = map(int, match.group(1, 2, 3))
    if second == 60:
        raise ValueError('LEAP_SECOND_REQUIRES_EXPLICIT_TIME_SCALE')
    if hour >= 24 or minute >= 60 or second >= 60:
        raise ValueError('TIME_RANGE')
    value = (day - EPOCH).days * DAY + (hour * 3600 + minute * 60 + second) * NS
    value += int((match[4] or '').ljust(9, '0'))
    if not 0 < value < 2**63:
        raise ValueError('UTC_INT64_RANGE')
    return value


def rmc_day(text):
    if not re.fullmatch(r'\d{6}', text):
        raise ValueError('RMC_DATE_MISSING_OR_INVALID')
    yy = int(text[4:])
    # Explicit legacy-compatible 1969..2068 interpretation, independently checked by KSXT.
    return dt.date((2000 if yy <= 68 else 1900) + yy, int(text[2:4]), int(text[:2]))


class Adapter:
    def __init__(self):
        self.date_reference_ns = None

    def parse(self, raw):
        check = checksum(raw)
        text = raw.rstrip(b'\r\n').decode('ascii', errors='replace')
        token = text.split(',', 1)[0]
        source = token[1:] if token in ('#AGRICA', '#UNIHEADINGA', '$KSXT') else \
            token[-3:] if token.startswith('$G') else 'UNCLASSIFIED'
        result = dict(check, source=source, raw_text=text, utc_valid=False, utc_measurement_ns=0,
                      utc_candidate_ns=0, time_reason='NO_TIME_FIELD', time_fields={},
                      raw_quality=None, solution_quality=0, position_valid=False, pvt=None,
                      local_measurement_ns=0, local_measurement_time_valid=False,
                      valid_for_fusion=False, mapping_version=0,
                      timestamp_uncertainty_ns=None, measurement_to_mid_mapping='PENDING')
        if not check['checksum_valid']:
            result['parse_reason'] = check['checksum_reason']
            return result
        if source not in ('AGRICA', 'UNIHEADINGA', 'GGA', 'RMC', 'GST', 'GSA', 'KSXT', 'ZDA'):
            result['parse_reason'] = 'UNSUPPORTED_FORMAT_PRESERVED'
            return result
        q, p = None, None
        try:
            body = text[1:text.rindex('*')]
            fields = body.split(',')
            old = legacy.GnssParser()
            p = old._parse_agrica(text) if source == 'AGRICA' else old._parse_nmea(text)
            p.utc_ns, p.utc_valid = 0, False
            result['parse_reason'] = p.reject_reason
            q = None
            if source in ('AGRICA', 'UNIHEADINGA'):
                header, data = body.split(';', 1)
                h, d = header.split(','), data.split(',')
                if len(h) != 10:
                    raise ValueError('UNSUPPORTED_ASCII_HEADER_LAYOUT')
                result['time_fields'] = dict(zip(('reference', 'status', 'week', 'tow_ms',
                                                  'leap_seconds', 'output_delay_ms'),
                                                 (h[2], h[3], h[4], h[5], h[8], h[9])))
                if source == 'UNIHEADINGA':
                    if len(d) != 17:
                        raise ValueError('UNIHEADING_FIELD_COUNT')
                    result.update(heading_solution_status=d[0], heading_position_type=d[1],
                                  parse_reason='CLASSIFIED_CRC_CHECKED_RAW_PRESERVED',
                                  time_reason='HEADING_TIME_NOT_PROMOTED_TO_PVT')
                    return result
                if len(d) != 57 or d[0] != 'GNSS' or d[1] != '232':
                    raise ValueError('UNSUPPORTED_AGRICA_LAYOUT')
                q = int(d[8])
                result.update(raw_quality=q, agrica_heading_status=d[9],
                              raw_height=d[31], raw_undulation=d[50],
                              height_reference='AGRICA_HEIGHT_DATUM_UNRESOLVED')
                result['time_fields']['utc_calendar_fields'] = d[2:8]
                result['time_fields']['data_tow_ms'] = d[47]
                result['time_reason'] = 'GPS_TIME_UNKNOWN_OR_UNSUPPORTED_REFERENCE'
                if h[2] == 'GPS' and h[3] == 'FINE':
                    week, tow_ms, leap = int(h[4]), int(h[5]), int(h[8])
                    if not (0 <= week <= 65535 and 0 <= tow_ms < 604800000 and 0 <= leap <= 255):
                        raise ValueError('GPS_TIME_FIELD_RANGE')
                    if tow_ms != int(d[47]):
                        raise ValueError('HEADER_DATA_TOW_MISMATCH')
                    day = dt.date(2000 + int(d[2]), int(d[3]), int(d[4]))
                    calendar_ns = utc_ns(day, ''.join('%02d' % int(v) for v in d[5:8]))
                    value = GPS_EPOCH_NS + week * 7 * DAY + tow_ms * 1000000 - leap * NS
                    if value // NS != calendar_ns // NS:
                        raise ValueError('GPS_LEAP_UTC_CALENDAR_DISAGREE')
                    result.update(utc_candidate_ns=value, utc_measurement_ns=value, utc_valid=True,
                                  time_reason='GPS_FINE_MESSAGE_LEAP_CALENDAR_CHECKED')
            elif source == 'KSXT':
                if len(fields) != 22:
                    raise ValueError('KSXT_FIELD_COUNT')
                q_raw = int(fields[10]); q = {0: 0, 1: 1, 2: 5, 3: 4}.get(q_raw, 0)
                result.update(raw_quality=q_raw, raw_height=fields[4], height_reference='MSL_ONLY')
                p.latitude, p.longitude = float(fields[3]), float(fields[2])
                p.altitude, p.height_msl = float(fields[4]), float(fields[4])
                p.num_sv = int(fields[13])
                p.vel_e, p.vel_n, p.vel_d = (float(fields[17] or 0) / 3.6,
                                           float(fields[18] or 0) / 3.6,
                                           -float(fields[19] or 0) / 3.6)
                result['time_fields'] = {'utc_text': fields[1], 'position_quality': fields[10]}
                day = dt.date(int(fields[1][:4]), int(fields[1][4:6]), int(fields[1][6:8]))
                value = utc_ns(day, fields[1][8:])
                result.update(utc_candidate_ns=value, utc_valid=q_raw in (1, 2, 3),
                              time_reason='FULL_UTC_WITH_VALID_SOLUTION_NO_INDEPENDENT_TIME_STATUS')
                if result['utc_valid']:
                    result['utc_measurement_ns'] = value
            elif source == 'RMC':
                result['time_fields'] = {'utc_text': fields[1], 'date_text': fields[9],
                                        'status': fields[2], 'mode': fields[12] if len(fields) > 12 else '',
                                        'year_policy': '1969..2068; verify against four-digit date'}
                value = utc_ns(rmc_day(fields[9]), fields[1])
                valid = fields[2] == 'A' and (len(fields) <= 12 or fields[12] not in ('N', 'S'))
                result.update(utc_candidate_ns=value, utc_valid=valid,
                              utc_measurement_ns=value if valid else 0,
                              time_reason='RMC_ACTIVE_DATE_TIME' if valid else 'RMC_INVALID_STATUS')
            elif source in ('GGA', 'GST', 'ZDA'):
                if source == 'GGA':
                    q = int(fields[6]); result['raw_quality'] = q
                    result['height_reference'] = 'MSL_PLUS_GEOID'
                result['time_fields'] = {'utc_text': fields[1], 'date_reference_ns': self.date_reference_ns}
                if source == 'ZDA':
                    day = dt.date(int(fields[4]), int(fields[3]), int(fields[2]))
                    result['utc_candidate_ns'] = utc_ns(day, fields[1])
                    result['time_reason'] = 'ZDA_NO_INDEPENDENT_VALIDITY_STATUS'
                elif self.date_reference_ns is not None:
                    day = EPOCH + dt.timedelta(days=self.date_reference_ns // DAY)
                    value = utc_ns(day, fields[1])
                    result['utc_candidate_ns'] = value
                    if abs(value - self.date_reference_ns) <= NS and (source != 'GGA' or q in (1, 2, 4, 5)):
                        result.update(utc_measurement_ns=value, utc_valid=True,
                                      time_reason='FRESH_FULL_DATE_CONTEXT_WITHIN_1S')
                    else:
                        result['time_reason'] = 'DATE_STALE_OR_ROLLOVER_OR_INVALID_SOLUTION'
                else:
                    result['time_reason'] = 'DATE_UNAVAILABLE'
            if result['utc_valid'] and source in ('AGRICA', 'KSXT', 'RMC'):
                self.date_reference_ns = result['utc_measurement_ns']
        except (ValueError, IndexError, OverflowError) as error:
            result['time_reason'] = str(error)
        if q is not None:
            legacy.GnssParser._finish_position(p, q)
            result.update(solution_quality={0: 0, 1: 1, 2: 2, 5: 3, 4: 4}.get(q, 0),
                          position_valid=p.position_valid)
            # Do not label an unconfirmed height datum as ellipsoidal height.
            if source in ('KSXT', 'AGRICA'):
                p.altitude = math.nan
            p.utc_ns, p.utc_valid = result['utc_measurement_ns'], result['utc_valid']
            result['pvt'] = dataclasses.asdict(p)
            result['parse_reason'] = p.reject_reason
        return result
