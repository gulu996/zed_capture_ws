# Jetson ZED capture source backup

Requested on 2026-10-23 (Asia/Shanghai). Initial local Git snapshot; no remote push.

Includes current src, scripts, vendored dependencies with licenses, docs, diagnostic source/config/tests, field_capture include overrides, GNSS parser dependencies and selected baseline/release/build manifests. Original source bytes and executable modes preserved. CODE_BACKUP_SHA256.json hashes original file bytes (symlink target text for symlinks).

Excludes recordings, JPEGs, bags, logs, caches, build binaries, evidence directories and historical backup directories except the explicitly selected baseline hash file. .gitignore is an exact snapshot allowlist: explicitly review and add new source paths to it before future commits.

This is a source checkpoint, not a portable runtime image or a fresh-build validation. Current field_capture code uses build_continuous_v3 and frozen baseline hashes, including generated binaries. Those binaries are not committed. ROS Noetic, system libraries, /home/jetson/catkin_ws and other external dependencies are not bundled. Restoring on another machine needs a separate build/dependency/baseline review; do not bypass frozen checks or assume the saved release manifest is a new hardware validation.

No capture, ROS test, rebuild, system-time change or algorithm edit was performed for this backup. Commit identity reuses the user's configured local Git identity, supplied per command; global Git configuration is unchanged.
