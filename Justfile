set default-list := true
set dotenv-load := false

# Create .venv and install the package plus test extras.
setup:
    uv sync --extra dev

# Run unit tests. Extra args go to pytest, e.g. `just test -k protocol`.
[positional-arguments]
test *args:
    uv run pytest "$@"

# Hold-to-talk and type into the focused app. Extra args go to `yark listen`.
[positional-arguments]
listen *args:
    uv run yark listen "$@"

# Hold-to-talk, print transcript instead of typing.
[positional-arguments]
print *args:
    uv run yark listen --print "$@"

# Record until Enter. Extra args go to `yark once`.
[positional-arguments]
once *args:
    uv run yark once "$@"

# Check config, mic, and macOS permissions.
doctor:
    uv run yark doctor

# Write ~/.config/yark/config.toml if it does not exist.
init-config:
    uv run yark init-config
