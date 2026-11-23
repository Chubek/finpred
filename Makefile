.DEFAULT_GOAL := build

CMAKE ?= cmake
CTEST ?= ctest
MULIB_JOBS ?= 4
NATIVE_BUILD_DIR ?= build/native
TUI_REVIEW_BUILD_DIR ?= build/poindexter-tui-review

.PHONY: all build mulib test dragnet-test forecast-score-test native-test poindexter poindexter-gui poindexter-gui-test poindexter-tui-review

all: build

build:
	./bin/build.sh

mulib:
	CMAKE="$(CMAKE)" MULIB_JOBS="$(MULIB_JOBS)" sh ./bin/build-mulib.sh

test: build
	python3 tests/check_build_paths.py
	env -u FINPRED_EXE ./tests/run.sh
	$(MAKE) dragnet-test
	$(MAKE) forecast-score-test

dragnet-test:
	set -eu; . ./bin/build-env.sh; finpred_build_env "$(CURDIR)"; \
		python3 tests/check_dragnet_frozen_csv.py; \
		python3 tests/check_dragnet_elvi.py; \
		python3 tests/check_crossref_replay.py; \
		python3 tests/check_dragnet_public_feeds.py; \
		python3 tests/check_dragnet_dispatch.py

forecast-score-test:
	set -eu; . ./bin/build-env.sh; finpred_build_env "$(CURDIR)"; \
		python3 tests/check_forecast_scores.py

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
