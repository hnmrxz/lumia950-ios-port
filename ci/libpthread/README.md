# The pthread component, taken from upstream instead of written here

`scripts/build-libpthread-kernel.py` in UniXNU at our pin builds the **Darwin 23** pthread
component (its docstring says so, and its `REVISION` is pinned to the Darwin 23 source). This
port runs the iOS 16.7.16 kernel, `xnu-8796.141.3` / Darwin 22, so that component cannot link
against it: the kernel side of a newer libpthread references symbols and records this kernel
does not have.

Upstream has since made the same builder profile-driven, which is exactly the gap:

- it takes `UNIXNU_LIBPTHREAD_COMMIT` from the environment instead of a hardcoded revision;
- it compiles for `kernel_target.TRIPLE` and audits each object;
- it re-creates its work tree when the reference revision differs.

The two files here are that upstream version, copied verbatim (`UniXNU/UniXNU@main`, fetched
2026-11-23) so the kernel job can use them without forking the framework:

- `build-libpthread-kernel.py`
- `kernel_target.py`

For the Darwin 22 line the source is Apple's `libpthread-519.101.1`, whose commit is
`ea29c4ab45a49dd44d564a093b1c9ce9d58610bc`; the framework's own feed pins `libpthread-519.120.4`
for Darwin 23, so the job has to fetch and name the older revision explicitly.

Nothing here is invented: when upstream's builder learns about the 16.x line, these files go
away and the pin moves instead.
