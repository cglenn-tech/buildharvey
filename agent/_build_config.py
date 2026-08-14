"""
Build-time configuration constants.

In a production privacy build, PRODUCTION_BUILD is set to True by the CI/CD
pipeline before packaging. This constant is baked into the binary and cannot
be changed at runtime via environment variables or flags.

When PRODUCTION_BUILD=True:
  - PRIVATE_MODE is forced to True regardless of BUILDHARVEY_PRIVATE_MODE env var
  - Any attempt to import or call cloud work-content paths raises RuntimeError
  - ENABLE_CAPTURE_LEASES and USE_LOCAL_INFERENCE are forced to True
  - This cannot be reverted by users, operators, or server configuration

For development/CI: leave PRODUCTION_BUILD=False (the default here).
The CI workflow sets BUILDHARVEY_PRIVATE_MODE=false to test cloud paths.

For production installer build: the build script patches this file to set
PRODUCTION_BUILD=True before PyInstaller packages the binary.
"""

# Set to True by build pipeline for production packages.
# Never set this True manually in the source tree — only the build script should.
PRODUCTION_BUILD: bool = False
