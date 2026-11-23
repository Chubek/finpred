.DEFAULT_GOAL := build

CMAKE ?= cmake
CTEST ?= ctest
MULIB_JOBS ?= 4
NATIVE_BUILD_DIR ?= build/native
TUI_REVIEW_BUILD_DIR ?= build/poindexter-tui-review

.PHONY: all build mulib test native-test poindexter poindexter-gui poindexter-gui-test poindexter-tui-review

all: build

build:
	./bin/build.sh

mulib:
	. ./bin/build-env.sh && finpred_build_env "$(CURDIR)" && \
	root=$$(realpath "$${MULIB_ROOT:-$(CURDIR)/third_party/mulib}") && \
	$(CMAKE) -S "$$root/on1x" -B build/mulib/on1x \
		-DBUILD_TESTING=ON -DON1X_REQUIRE_LIBSTONE=ON \
		-DON1X_BUILD_NATIVE_PPX=ON -DON1X_BUILD_GRAMMAREMBED=ON \
		-DON1X_LIBSTONE_ROOT="$$root/on1x/third_party/libstone" && \
	$(CMAKE) --build build/mulib/on1x --parallel "$(MULIB_JOBS)" --target on1xc on1x_ppx_GrammarEmbed

test: build
	out=$$(realpath -m -- "$${FINPRED_BUILD_DIR:-build/dev}") && FINPRED_EXE="$$out/finpred" ./tests/run.sh

native-test:
	$(CMAKE) -S native -B "$(NATIVE_BUILD_DIR)" -DBUILD_TESTING=ON -DCMAKE_C_FLAGS='-Wall -Wextra -Werror -pedantic'
	$(CMAKE) --build "$(NATIVE_BUILD_DIR)"
	$(CTEST) --test-dir "$(NATIVE_BUILD_DIR)" --output-on-failure --no-tests=error

poindexter:
	./bin/poindexter --build

poindexter-gui: poindexter
	bash plugins/poindexter/gui/build.sh

poindexter-gui-test:
	. ./bin/build-env.sh && finpred_build_env "$(CURDIR)" && python3 tests/check_poindexter_gui.py

poindexter-tui-review:
	$(CMAKE) -S plugins/poindexter/workbench/native -B "$(TUI_REVIEW_BUILD_DIR)" \
		-DMULIB_ROOT="$${MULIB_ROOT:-$(CURDIR)/third_party/mulib}" \
		-DBUILD_TESTING=ON -DCMAKE_C_FLAGS='-Wall -Wextra -Werror -pedantic'
	$(CMAKE) --build "$(TUI_REVIEW_BUILD_DIR)"
	$(CTEST) --test-dir "$(TUI_REVIEW_BUILD_DIR)" --output-on-failure --no-tests=error
