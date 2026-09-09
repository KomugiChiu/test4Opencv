# Camera toolkit prebuilt flow (selfbuild / arm64 / target-fetch testdata).
# ARCH=native (default) or ARCH=aarch64 for x86_64 -> aarch64 cross.
# make install assembles ./install/ (relocatable, runnable in place, no /opt needed).
ARCH ?= native
OPENCV_TEST_BUILD_DIR ?= $(if $(filter aarch64,$(ARCH)),build/aarch64,build/latest)
JOBS ?= $(shell nproc)
PREFIX ?= /opt/camera-toolkit
INSTALL_DIR ?= install

.PHONY: prebuild package verify verify-cross install install-target clean clean-all help
help:
	@echo "targets: prebuild | package | verify | verify-cross | install | clean | clean-all  (ARCH=native|aarch64)"

prebuild:
	bash scripts/build_prebuilt.sh --arch $(ARCH) --opencv-test-build-dir $(OPENCV_TEST_BUILD_DIR) --jobs $(JOBS)

package:
	bash scripts/package_prebuilt.sh --arch $(ARCH) --opencv-test-build-dir $(OPENCV_TEST_BUILD_DIR)

verify:
	bash scripts/verify_prebuilt.sh --opencv-test-build-dir $(OPENCV_TEST_BUILD_DIR)

verify-cross:
	bash scripts/verify_cross.sh --opencv-test-build-dir $(OPENCV_TEST_BUILD_DIR)

install: package
	bash scripts/install_prebuilt.sh --tarball "$$(ls -t dist/*.tar.gz | head -n 1)" \
		--prefix $(INSTALL_DIR) --fetch-testdata skip --no-apt --force-arch

install-target:
	@echo "on target board: sudo bash scripts/install_prebuilt.sh --tarball dist/<name>.tar.gz --prefix $(PREFIX) --fetch-testdata full --yes"

# clean: consumer build dirs + dist + install/ (keeps opencv build + source + testdata)
CONSUMER_BUILDS := auto_cpp/build manual_cpp/build auto_cpp/build-aarch64 manual_cpp/build-aarch64
clean:
	rm -rf $(CONSUMER_BUILDS) dist $(INSTALL_DIR)

# clean-all: also drops opencv build trees (rebuild takes a long time)
clean-all: clean
	rm -rf build/latest build/aarch64
