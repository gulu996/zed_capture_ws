"""Restricted, byte-preserving extension; the hash-pinned R1 stays unchanged.

Only the observed empty-position NO_FIX G[NP]GGA prefix is recoverable here.
Other corruption remains raw evidence until separately validated.
"""
import re
from gnss_r1_compat import checksum, split_record as r1_split_record


def split_record(raw):
    # A valid complete parent always wins, even if it contains a start marker.
    if checksum(raw)['checksum_valid']:
        return [(raw, 'NONE')]
    old = r1_split_record(raw)
    if old != [(raw, 'NONE')]:
        return old
    # No scanning arbitrary payloads: anchored, bounded known NO_FIX grammar.
    match = re.fullmatch(
        rb'(\$G[NP]GGA,,,,,,0,{1,8})(\$G[NP]RMC,[^$#*\r\n]*\*[0-9A-Fa-f]{2}(?:\r\n|\r|\n))', raw)
    if not match:
        return old
    prefix, tail = match.groups()
    # 12-field older RMC or 13/14-field optional mode/navigation status forms.
    fields = tail.rstrip(b'\r\n').split(b'*')[0].split(b',')
    if len(fields) not in (12, 13, 14) or fields[2] not in (b'A', b'V'):
        return old
    if not checksum(tail)['checksum_valid']:
        return old
    return [(prefix, 'TRUNCATED_GGA_BEFORE_VALID_RMC'),
            (tail, 'RESYNC_AFTER_TRUNCATED_GGA')]
