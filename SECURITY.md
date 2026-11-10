# Security model and local-account isolation

## High-severity finding in v1.2.2 and earlier

Commit `243e336b7e4860c2ed38aa10ca7dc27386d6d3e7` exposed unauthenticated host
loopback TCP endpoints on 5909 and 5910 while the monitor was active. Another
host account could read its display and, with input enabled, inject desktop
input. USB debugging authorization did not protect those TCP endpoints.
Loopback is not a user-authentication boundary. The original README documented
the access but that disclosure did not mitigate it.

Until updated, stop Omadesk with `omadesk stop`. Do not treat disabling remote
input as a complete fix: screen capture would still be exposed.

## v1.2.3 remediation

- No host VNC TCP listener, including localhost. WayVNC runs with `-u` on an
  owner-only filesystem Unix socket. Its control socket is private as well.
- The RFB quality proxy uses `ThreadingUnixStreamServer`, not TCP. Its socket
  has mode 0600 and every accepted peer is checked using Linux `SO_PEERCRED`.
- All transport paths are inside `$XDG_RUNTIME_DIR/omadesk`, mode 0700. Runtime
  ownership/permissions and directory symlinks are checked before use. Unsafe
  paths fail closed instead of falling back to TCP or abstract Unix sockets.
- Every ADB command explicitly uses `-L localfilesystem:.../adb.sock`. Using
  a shared same-UID ADB TCP daemon could reintroduce a privileged proxy around
  filesystem restrictions. Omadesk refuses a same-UID listener on the standard
  port 5037 before each ADB operation. It never automatically kills unrelated
  ADB daemons, and it must not be used alongside owner-run shared ADB servers
  on other ports. This check is a compatibility guard, not an instantaneous
  security monitor for arbitrary other software started by the owner.
- ADB reverse maps Android's localhost 5909 to the private host quality socket,
  not to a host TCP port. The host's existing WayVNC configuration is not edited;
  the dedicated `-C /dev/null` instance is isolated by Unix permissions/peer UID.

This protects against ordinary *different host UIDs*, not root, same-UID
processes, a compromised owner account, arbitrary insecure same-UID IPC services,
or malicious apps on the trusted Android device. Android localhost 5909 is not
app-private; apps on that device may access it while the USB tunnel is active.
Do not connect untrusted Android devices. No claim of sandboxing, end-to-end
encryption, per-Android-app authentication or general security certification is
made. ADB USB authentication remains required.

## Validation

`tests/test_secure_transport.py` checks private directory ownership/modes,
symlink rejection, foreign peer UID rejection, refusal of shared ADB, private
ADB routing despite TCP environment variables, and complete image/input RFB
exchange through Unix sockets. Host integration should additionally verify:

1. Start the monitor and confirm `omadesk status` reports connected.
2. Confirm `ss -ltn '( sport = :5909 or sport = :5910 or sport = :5037 )'`
   shows no listeners from Omadesk or an owner-run default ADB daemon.
3. Check all transport files under `$XDG_RUNTIME_DIR/omadesk` are owner-only.
4. From a genuinely different unprivileged UID, attempt connections to the
   WayVNC, proxy and ADB filesystem sockets: all must fail with permission denied.
5. Confirm legitimate AVNC image/input, stop cleanup and compositor reload
   recovery still work. A patch is not approved until maintainers re-review its
   **new exact commit**, rather than accepting the old reviewed SHA.

Report remaining vulnerabilities privately through the repository's GitHub
security reporting facility when available, rather than posting credentials,
private images, tokens or exploit material in a public issue.
