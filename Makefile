.DEFAULT_GOAL := build

CMAKE ?= cmake
CTEST ?= ctest
MULIB_JOBS ?= 4
NATIVE_BUILD_DIR ?= build/native
NATIVE_TEMPORAL_BUILD_DIR ?= build/native-temporal
TUI_REVIEW_BUILD_DIR ?= build/poindexter-tui-review

TEST_SUITES := compiler pricing forecasting plugins storage security
TEST_TARGETS := $(addprefix test-,$(TEST_SUITES))

.PHONY: all build mulib test $(TEST_TARGETS) caravansary caravansary-test caravansary-market-test dragnet dragnet-test dragnet-search-test forecast-score-test native-test native-temporal-test poindexter poindexter-gui poindexter-gui-test poindexter-tui-review

all: build

build:
	./bin/build.sh

mulib:
	CMAKE="$(CMAKE)" MULIB_JOBS="$(MULIB_JOBS)" sh ./bin/build-mulib.sh

test: build
	status=0; \
		env -u FINPRED_EXE ./tests/run.sh || status=1; \
		$(MAKE) native-test || status=1; \
		$(MAKE) native-temporal-test || status=1; \
		$(MAKE) poindexter-tui-review || status=1; \
		exit $$status

# Build the matching CLI/compiler first when running a selector locally.
# Like direct tests/run.sh, selectors can use an explicit FINPRED_EXE.
$(TEST_TARGETS): test-%:
	./tests/run.sh $*

test-storage: native-test native-temporal-test

test-plugins: poindexter-tui-review

caravansary:
	./bin/caravansary build

caravansary-test:
	./tests/run.sh caravansary

caravansary-market-test:
	./tests/run.sh caravansary-market

dragnet-test:
	./tests/run.sh dragnet-legacy

dragnet-search-test:
	./tests/run.sh dragnet-search

dragnet:
	./bin/dragnet --build

forecast-score-test:
	./tests/run.sh forecast-score

native-test:
	$(CMAKE) -S native -B "$(NATIVE_BUILD_DIR)" -DBUILD_TESTING=ON -DCMAKE_C_FLAGS='-Wall -Wextra -Werror -pedantic'
	$(CMAKE) --build "$(NATIVE_BUILD_DIR)"
	$(CTEST) --test-dir "$(NATIVE_BUILD_DIR)" --output-on-failure --no-tests=error

native-temporal-test:
	$(CMAKE) -S native -B "$(NATIVE_TEMPORAL_BUILD_DIR)" -DBUILD_TESTING=ON \
	  -DFINPRED_TEMPORAL_MULIB_ROOT="$${MULIB_ROOT:-$(CURDIR)/third_party/mulib}" \
	  -DCMAKE_C_FLAGS='-Wall -Wextra -Werror -pedantic'
	$(CMAKE) --build "$(NATIVE_TEMPORAL_BUILD_DIR)"
	$(CTEST) --test-dir "$(NATIVE_TEMPORAL_BUILD_DIR)" --output-on-failure --no-tests=error \
	  -R '^native_temporal_oracle_and_recovery$$'

poindexter:
	./bin/poindexter --build

poindexter-gui: poindexter
	sh ./bin/with-legacy-mulib.sh bash plugins/poindexter/gui/build.sh

poindexter-gui-test:
	sh ./bin/with-legacy-mulib.sh python3 tests/check_poindexter_gui.py

poindexter-tui-review:
	sh ./bin/with-legacy-mulib.sh sh -ec '\
	  $(CMAKE) -S plugins/poindexter/workbench/native -B "$(TUI_REVIEW_BUILD_DIR)" \
	    -DMULIB_ROOT="$$MULIB_ROOT" -DBUILD_TESTING=ON -DCMAKE_C_FLAGS="-Wall -Wextra -Werror -pedantic"; \
	  $(CMAKE) --build "$(TUI_REVIEW_BUILD_DIR)"; \
	  $(CTEST) --test-dir "$(TUI_REVIEW_BUILD_DIR)" --output-on-failure --no-tests=error'
