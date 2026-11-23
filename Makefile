.DEFAULT_GOAL := build

CMAKE ?= cmake
CTEST ?= ctest
NATIVE_BUILD_DIR ?= build/native
TUI_REVIEW_BUILD_DIR ?= build/poindexter-tui-review

.PHONY: all build test native-test poindexter poindexter-gui poindexter-gui-test poindexter-tui-review

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

poindexter-gui: poindexter
	bash plugins/poindexter/gui/build.sh

poindexter-gui-test:
	python3 tests/check_poindexter_gui.py

poindexter-tui-review:
	$(CMAKE) -S plugins/poindexter/workbench/native -B "$(TUI_REVIEW_BUILD_DIR)" \
		-DMULIB_ROOT="$${MULIB_ROOT:-$(CURDIR)/third_party/mulib}" \
		-DBUILD_TESTING=ON -DCMAKE_C_FLAGS='-Wall -Wextra -Werror -pedantic'
	$(CMAKE) --build "$(TUI_REVIEW_BUILD_DIR)"
	$(CTEST) --test-dir "$(TUI_REVIEW_BUILD_DIR)" --output-on-failure --no-tests=error
