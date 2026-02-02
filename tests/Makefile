SHELL := /bin/bash
.DEFAULT_GOAL := help

# =============================================================================
# Configuration
# =============================================================================

TESTENV      := .testenv
KEYS_DIR     := $(TESTENV)/keys
IGN_DIR      := $(TESTENV)/ignition
ISO_DIR      := .iso

# VM selection (min, full, or all)
VM           ?= all

# FCOS settings
FCOS_ARCH    ?= aarch64
FCOS_STREAM  := https://builds.coreos.fedoraproject.org/streams/stable.json

# ISO files
FCOS_ISO_LIVE := $(TESTENV)/live.iso

# Podman: coreos-installer
COREOS_INSTALLER := podman run --rm --pull=newer --security-opt label=disable \
	-v $(CURDIR)/$(ISO_DIR):/iso:ro \
	-v $(CURDIR)/$(TESTENV):/out \
	quay.io/coreos/coreos-installer:release

# Test container
TEST_IMAGE       := fcos-test-runner:v1
COLLECTION_DIR   := $(CURDIR)/..

# Ansible environment for compact output
ANSIBLE_RUN      := podman run --rm --security-opt label=disable \
	--network host \
	-e ANSIBLE_DISPLAY_SKIPPED_HOSTS=false \
	-e ANSIBLE_DISPLAY_OK_HOSTS=false \
	-v $(CURDIR):/ansible/tests:ro \
	-v $(CURDIR)/$(TESTENV):/ansible/tests/.testenv \
	-v $(COLLECTION_DIR):/ansible/collections/ansible_collections/kudato/fcos:ro \
	-w /ansible/tests \
	$(TEST_IMAGE) \
	-i inventory.yml --private-key /ansible/tests/.testenv/keys/test_key

# SSH key and known hosts
SSH_KEY      := $(KEYS_DIR)/test_key
SSH_KEY_PUB  := $(SSH_KEY).pub
KNOWN_HOSTS  := $(TESTENV)/known_hosts

# Keep VM after test
KEEP_VM      ?=

# Debug mode (adds -vvv to ansible)
DEBUG        ?=
ANSIBLE_VERBOSE := $(if $(DEBUG),-vvv,)

# Boot mode: DISK=1 boots from installed disk, otherwise from live ISO
DISK         ?=
BOOT_MODE    := $(if $(DISK),--disk,--live)

# =============================================================================
# Help
# =============================================================================

.PHONY: help
help:
	@echo "FCOS E2E Testing"
	@echo "================"
	@echo ""
	@echo "Quick Start:"
	@echo "  make setup              Prepare environment (ISO, keys, container)"
	@echo "  make test               Run full E2E test"
	@echo ""
	@echo "Development:"
	@echo "  make start              Start VM(s) (DISK=1 for disk boot)"
	@echo "  make ssh VM=<name>      SSH into VM"
	@echo "  make console VM=<name>  Interactive serial console (Ctrl+O to exit)"
	@echo "  make log VM=<name>      Follow console log (tail -f)"
	@echo "  make stop               Stop VM(s)"
	@echo ""
	@echo "Testing Steps:"
	@echo "  make validate           Run validation tests (no VM needed)"
	@echo "  make install            Run Ansible installation"
	@echo "  make restart            Restart VM(s) to boot from disk"
	@echo "  make verify             Run verification tests"
	@echo ""
	@echo "Utilities:"
	@echo "  make status             Show VM status"
	@echo "  make clean              Remove .testenv (keep ISO)"
	@echo "  make clean-all          Remove everything"
	@echo ""
	@echo "Options:"
	@echo "  VM=min|full|all         Target VM (default: all)"
	@echo "  DISK=1                  Boot from installed disk (default: live ISO)"
	@echo "  KEEP_VM=1               Keep VMs after test"
	@echo "  DEBUG=1                 Verbose Ansible output (-vvv)"

# =============================================================================
# Setup
# =============================================================================

.PHONY: _check-deps
_check-deps:
	@command -v qemu-system-$(FCOS_ARCH) >/dev/null 2>&1 || { echo "✗ qemu-system-$(FCOS_ARCH) not found"; exit 1; }
	@command -v podman >/dev/null 2>&1 || { echo "✗ podman not found"; exit 1; }
	@command -v jq >/dev/null 2>&1 || { echo "✗ jq not found"; exit 1; }
	@command -v curl >/dev/null 2>&1 || { echo "✗ curl not found"; exit 1; }

.PHONY: setup
setup: _check-deps $(SSH_KEY) $(KNOWN_HOSTS) _ensure-iso $(IGN_DIR)/live.ign _customize-iso _build-test-image
	@echo "✓ Setup complete. Run 'make test' to start testing."

$(KNOWN_HOSTS):
	@touch $(KNOWN_HOSTS)

$(SSH_KEY):
	@echo "→ Generating SSH key..."
	@mkdir -p $(KEYS_DIR)
	@ssh-keygen -t ed25519 -f $(SSH_KEY) -N "" -C "fcos-test" -q
	@chmod 600 $(SSH_KEY)

.PHONY: _ensure-iso
_ensure-iso:
	@mkdir -p $(ISO_DIR)
	@if [ -z "$$(ls $(ISO_DIR)/*.iso 2>/dev/null)" ]; then \
		echo "→ Downloading FCOS ISO (this may take a while)..."; \
		URL=$$(curl -s $(FCOS_STREAM) | jq -r '.architectures.$(FCOS_ARCH).artifacts.metal.formats.iso.disk.location'); \
		curl -L --progress-bar -o $(ISO_DIR)/$$(basename $$URL) "$$URL"; \
	else \
		echo "→ Using existing ISO: $$(basename $$(ls -t $(ISO_DIR)/*.iso | head -1))"; \
	fi

$(IGN_DIR)/live.ign: $(SSH_KEY)
	@mkdir -p $(IGN_DIR)
	@SSH_PUB=$$(cat $(SSH_KEY_PUB)) && \
	 echo '{"ignition":{"version":"3.4.0"},"passwd":{"users":[{"name":"core","sshAuthorizedKeys":["'"$$SSH_PUB"'"]}]}}' > $@

.PHONY: _customize-iso
_customize-iso: $(IGN_DIR)/live.ign
	@if [ ! -f $(FCOS_ISO_LIVE) ] || [ $(IGN_DIR)/live.ign -nt $(FCOS_ISO_LIVE) ]; then \
		ISO_FILE=$$(ls -t $(ISO_DIR)/*.iso 2>/dev/null | head -1); \
		if [ -z "$$ISO_FILE" ]; then \
			echo "✗ No ISO found in $(ISO_DIR). Run 'make setup' first."; \
			exit 1; \
		fi; \
		echo "→ Customizing ISO with ignition (podman)..."; \
		rm -f $(FCOS_ISO_LIVE); \
		$(COREOS_INSTALLER) iso customize \
			--live-ignition /out/ignition/live.ign \
			-o /out/live.iso \
			/iso/$$(basename $$ISO_FILE); \
	else \
		echo "→ Using existing customized ISO"; \
	fi

.PHONY: _build-test-image
_build-test-image:
	@if ! podman image exists $(TEST_IMAGE); then \
		echo "→ Building test container..."; \
		podman build -t $(TEST_IMAGE) -f Containerfile $(COLLECTION_DIR); \
	else \
		echo "→ Using existing test container"; \
	fi

# =============================================================================
# Full E2E Test
# =============================================================================

.PHONY: test
test: setup validate
	@trap '[ -n "$(KEEP_VM)" ] || ./vm.py stop $(VM)' EXIT; \
	./vm.py create $(VM) && \
	./vm.py start $(VM) && \
	./vm.py wait $(VM) && \
	$(MAKE) --no-print-directory install VM=$(VM) && \
	./vm.py restart $(VM) && \
	./vm.py wait $(VM) && \
	$(MAKE) --no-print-directory verify VM=$(VM)
	@echo ""
	@printf '\033[1;32m═══════════════════════════════════════════════════════════════════\033[0m\n'
	@printf '\033[1;32m ✓ All tests passed\033[0m\n'
	@printf '\033[1;32m═══════════════════════════════════════════════════════════════════\033[0m\n'

# =============================================================================
# Validation Tests (no VM needed)
# =============================================================================

# Ansible run for localhost (validation tests)
ANSIBLE_RUN_LOCAL := podman run --rm --security-opt label=disable \
	-e ANSIBLE_DISPLAY_SKIPPED_HOSTS=false \
	-e ANSIBLE_DISPLAY_OK_HOSTS=false \
	-v $(CURDIR):/ansible/tests:ro \
	-v $(COLLECTION_DIR):/ansible/collections/ansible_collections/kudato/fcos:ro \
	-w /ansible/tests \
	$(TEST_IMAGE) \
	-i inventory.yml

.PHONY: validate
validate: _build-test-image
	@echo ""
	@printf '\033[1;33m═══════════════════════════════════════════════════════════════════\033[0m\n'
	@printf '\033[1;33m Running validation tests\033[0m\n'
	@printf '\033[1;33m═══════════════════════════════════════════════════════════════════\033[0m\n'
	@$(ANSIBLE_RUN_LOCAL) $(ANSIBLE_VERBOSE) test_install.yml --tags validate -l localhost

# =============================================================================
# Individual Steps
# =============================================================================

.PHONY: install
install:
	@echo ""
	@printf '\033[1;36m═══════════════════════════════════════════════════════════════════\033[0m\n'
	@printf '\033[1;36m Installing FCOS\033[0m\n'
	@printf '\033[1;36m═══════════════════════════════════════════════════════════════════\033[0m\n'
	@$(ANSIBLE_RUN) $(ANSIBLE_VERBOSE) test_install.yml $(if $(filter-out all,$(VM)),-l $(VM))

.PHONY: verify
verify:
	@echo ""
	@printf '\033[1;35m═══════════════════════════════════════════════════════════════════\033[0m\n'
	@printf '\033[1;35m Verifying installation\033[0m\n'
	@printf '\033[1;35m═══════════════════════════════════════════════════════════════════\033[0m\n'
	@$(ANSIBLE_RUN) $(ANSIBLE_VERBOSE) verify_install.yml $(if $(filter-out all,$(VM)),-l $(VM))

# =============================================================================
# VM Management (delegates to vm.py)
# =============================================================================

.PHONY: start
start: setup
ifeq ($(DISK),)
	@./vm.py create $(VM)
endif
	@./vm.py start $(BOOT_MODE) $(VM)
	@./vm.py wait $(VM)
	@./vm.py status

.PHONY: stop
stop:
	@./vm.py stop $(VM)

.PHONY: status
status:
	@./vm.py status

.PHONY: ssh
ssh:
ifeq ($(VM),all)
	@echo "Error: VM parameter required. Usage: make ssh VM=min|full"
	@exit 1
else
	@./vm.py ssh $(VM)
endif

.PHONY: console
console:
ifeq ($(VM),all)
	@echo "Error: VM parameter required. Usage: make console VM=min|full"
	@exit 1
else
	@./vm.py console $(VM)
endif

.PHONY: log
log:
ifeq ($(VM),all)
	@echo "Error: VM parameter required. Usage: make log VM=min|full"
	@exit 1
else
	@./vm.py log $(VM)
endif

.PHONY: restart
restart:
	@> $(KNOWN_HOSTS)
	@./vm.py restart $(VM)
	@./vm.py wait $(VM)
	@echo "✓ Restart complete"

# =============================================================================
# Utilities
# =============================================================================

.PHONY: rebuild-image
rebuild-image:
	@echo "→ Rebuilding test container..."
	@podman rmi -f $(TEST_IMAGE) 2>/dev/null || true
	@podman build -t $(TEST_IMAGE) -f Containerfile $(COLLECTION_DIR)
	@echo "✓ Test container rebuilt"

# =============================================================================
# Cleanup
# =============================================================================

.PHONY: clean
clean:
	@./vm.py stop all 2>/dev/null || true
	@echo "→ Cleaning (keeping ISO)..."
	@rm -rf $(TESTENV)
	@echo "✓ Clean complete"

.PHONY: clean-all
clean-all:
	@./vm.py stop all 2>/dev/null || true
	@echo "→ Full cleanup..."
	@rm -rf $(TESTENV) $(ISO_DIR)
	@podman rmi -f $(TEST_IMAGE) 2>/dev/null || true
	@echo "✓ Full clean complete"
