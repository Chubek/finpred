.DEFAULT_GOAL := build

CMAKE ?= cmake
CTEST ?= ctest
NATIVE_BUILD_DIR ?= build/native

.PHONY: all build test native-test poindexter

all: build

build:
	./bin/build.sh

test: build
	out=$$(realpath -m -- "$${FINPRED_BUILD_DIR:-target/dev}") && FINPRED_EXE="$$out/finpred" ./tests/run.sh

native-test:
	$(CMAKE) -S native -B "$(NATIVE_BUILD_DIR)" -DBUILD_TESTING=ON -DCMAKE_C_FLAGS='-Wall -Wextra -Werror -pedantic'
	$(CMAKE) --build "$(NATIVE_BUILD_DIR)"
	$(CTEST) --test-dir "$(NATIVE_BUILD_DIR)" --output-on-failure --no-tests=error

poindexter:
	./bin/poindexter --build
