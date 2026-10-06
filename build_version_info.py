"""Windows version-resource generation for the packaged executable.

Ported from Modan2 (its devlog 285), where a build stamped 0.0.0.0 on every
release and Inno Setup's version check silently kept the old exe on upgrade.
PaperMeister.spec imports this on Windows; tests/test_build_version_info.py
covers it. The installer also marks the payload ``ignoreversion`` -- both,
because either failing silently is what that bug cost.
"""

import re
import tempfile
from datetime import datetime
from pathlib import Path


def windows_file_version(version: str, build_number: str) -> tuple[int, int, int, int]:
    """The four numbers Windows records as a binary file version.

    Inno Setup compares *these*, not the human-readable string, when deciding
    whether an already-installed file is newer than the one being installed. Two
    rules follow, and breaking either silently blocks upgrades:

    1. **It must change between releases.** It did not, and the payload stopped
       being replaced entirely -- see prepare_version_info_file.
    2. **It must change between prereleases of the same x.y.z.** Only digits fit
       here, so "-alpha" and "-beta" are unrepresentable: scraping digits out of
       the whole version string gave 0.2.0-alpha.2 and 0.2.0-beta.2 the same
       (0, 2, 0, 2), which makes the second look like a reinstall of the first.

    Hence the build number in the fourth field rather than the prerelease
    ordinal. It is the commit count, so it rises across releases *and* across
    prereleases of one -- exactly the ordering Inno needs. Development builds
    have no build number and get 0.
    """
    parts = re.findall(r"\d+", version.split("-")[0])
    nums = [int(p) for p in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    build = int(build_number) if str(build_number).isdigit() else 0
    return (nums[0], nums[1], nums[2], build)


def prepare_version_info_file(version: str, app_name: str, build_number: str) -> str:
    """Write the PyInstaller --version-file for the Windows executable.

    Generated outright, with no template on disk. It used to read
    build/file_version_info.txt and fall back to a hardcoded default if that was
    missing -- and the file has never existed in the repository, while build/ is
    git-ignored, so *every* CI build took the fallback. The fallback stamped
    0.0.0.0 and contained none of the {{placeholders}} the substitution below it
    was replacing, so that substitution was a no-op that could not be seen.

    The consequence was not a cosmetic wrong number in the file properties.
    Every release carried the identical 0.0.0.0, so Inno's default version check
    ("the installed file is not older, keep it") skipped Modan2.exe on upgrade:
    the installer reported success and the previous build kept launching. Found
    installing 0.2.0-beta.3 over beta.2, and true of every upgrade before it.

    A missing template therefore must not be survivable, and now there is none
    to miss. The installer no longer relies on this alone either -- the payload
    is marked ignoreversion, so replacement does not depend on these numbers
    being right. Both, because either one failing silently is what this cost.
    """
    vt = windows_file_version(version, build_number)
    version_str = ".".join(str(n) for n in vt)
    # String fields are free text shown in the file's properties, so they carry
    # the version a human recognises. Only the tuple above is what Inno compares.
    display = f"{version} (build {build_number})"
    company = "PaleoBytes"
    copyright_str = f"(c) {datetime.now().astimezone().year} {company}"
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vt},
    prodvers={vt},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', {company!r}),
        StringStruct('FileDescription', {app_name!r}),
        StringStruct('FileVersion', {version_str!r}),
        StringStruct('InternalName', {f"{app_name}.exe"!r}),
        StringStruct('LegalCopyright', {copyright_str!r}),
        StringStruct('OriginalFilename', {f"{app_name}.exe"!r}),
        StringStruct('ProductName', {app_name!r}),
        StringStruct('ProductVersion', {display!r})
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

    tmp_dir = Path(tempfile.mkdtemp())
    out_path = tmp_dir / "file_version_info.txt"
    out_path.write_text(content, encoding="utf-8")
    return str(out_path)
