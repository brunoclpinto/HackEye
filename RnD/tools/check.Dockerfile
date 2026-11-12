# Gate image for tools/check.sh: the Lab image plus pinned ruff + mypy. Lab runtime image is untouched.
FROM hackeye-rnd
RUN pip install --no-cache-dir ruff==0.14.0 mypy==1.18.2
ENTRYPOINT []
