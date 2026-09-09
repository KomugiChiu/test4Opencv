# Camera toolkit prebuilt flow (selfbuild / arm64 / target-fetch testdata).
# ARCH=native (default) or ARCH=aarch64 for x86_64 -> aarch64 cross.
# make install assembles ./install/ (relocatable, runnable in place, no /opt needed).
ARCH ?= native
BUILD_DIR ?= $(if $(filter aarch64,$(ARCH)),build/aarch64,build/latest)
JOBS ?= $(shell nproc)
PREFIX ?= /opt/camera-toolkit
INSTALL_DIR ?= install

.PHONY: prebuild package verify verify-cross install help
help:
	@echo "targets: prebuild | package | verify | verify-cross | install  (ARCH=native|aarch64)"

prebuild:
	bash scripts/build_prebuilt.sh --arch $(ARCH) --build-dir $(BUILD_DIR) --jobs $(JOBS)

package:
	bash scripts/package_prebuilt.sh --arch $(ARCH) --build-dir $(BUILD_DIR)

verify:
	bash scripts/verify_prebuilt.sh --build-dir $(BUILD_DIR)

verify-cross:
	bash scripts/verify_cross.sh --build-dir $(BUILD_DIR)

install: package
	bash scripts/install_prebuilt.sh --tarball "$$(ls -t dist/*.tar.gz | head -n 1)" \
		--prefix $(INSTALL_DIR) --fetch-testdata skip --no-apt

install-target:
	@echo "on target board: sudo bash scripts/install_prebuilt.sh --tarball dist/<name>.tar.gz --prefix $(PREFIX) --fetch-testdata full --yes"
