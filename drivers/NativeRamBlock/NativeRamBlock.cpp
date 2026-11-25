// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// NativeRamBlock: the synthetic root media, as an IOBlockStorageDevice.
//
// The kernel waits for an IOMedia whose content is Apple_HFS (docs/emulation/2026-11-25-bsd-init-crossed.md).
// IOBlockStorageDriver builds that IOMedia from a storage device, so this provides the device, the
// geometry and the characteristic that names the content. The buffer is the whole medium and it is
// read-only on purpose: the point is a mount attempt, not a writable volume.

#include <pexpert/pexpert.h>
#include <IOKit/IOBufferMemoryDescriptor.h>

#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSString.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSBoolean.h>

#include "NativeRamBlock.h"

using namespace native_ram_block;

OSDefineMetaClassAndStructors(NativeRamBlock, IOBlockStorageDevice)

extern "C" {
// Visible in the symbol table: a boot with no console still says whether the media appeared.
volatile uint32_t native_ramblock_ready = 0;
volatile uint64_t native_ramblock_bytes = 0;
volatile uint64_t native_ramblock_reads = 0;
volatile uint64_t native_ramblock_errors = 0;
}

bool
NativeRamBlock::start(IOService *provider)
{
	if (!IOBlockStorageDevice::start(provider)) {
		return false;
	}

	// Geometry from the boot argument, so QEMU and the handset differ only in the number.
	uint64_t bytes = kDefaultBytes;
	(void)PE_parse_boot_argn("ramblock_bytes", &bytes, sizeof(bytes));
	geometry = geometry_for(bytes);
	if (!geometry.valid()) {
		native_ramblock_errors++;
		return false;
	}

	storage = IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task,
	    kIODirectionInOut, (vm_size_t)geometry.bytes, PAGE_SIZE);
	if (storage == nullptr) {
		native_ramblock_errors++;
		return false;
	}
	if (storage->prepare() != kIOReturnSuccess) {
		native_ramblock_errors++;
		return false;
	}
	// A zeroed medium: reads succeed, so the VFS rung gets a read path; HFS will reject the contents,
	// which is the next thing to fix and is not something this device pretends to have solved.
	bzero(storage->getBytesNoCopy(), (vm_size_t)geometry.bytes);

	// State the content on the device: the characteristics override is not part of this
	// ABI build, so the property is where the hint can live.
	setProperty("Content Hint", kContentHint);
	setProperty("Block Size", (unsigned long long)geometry.blockSize, 64);
	setProperty("Block Count", (unsigned long long)geometry.blockCount, 64);

	IOLog("NativeRamBlock: starting, %llu bytes, %llu blocks\n",
	    (unsigned long long)geometry.bytes, (unsigned long long)geometry.blockCount);

	ready = true;
	registerService();
	IOLog("NativeRamBlock: media published\n");

	native_ramblock_bytes = geometry.bytes;
	native_ramblock_ready = 1;
	return true;
}

void
NativeRamBlock::stop(IOService *provider)
{
	ready = false;
	native_ramblock_ready = 0;
	if (storage != nullptr) {
		(void)storage->complete();
		storage->release();
		storage = nullptr;
	}
	IOBlockStorageDevice::stop(provider);
}

void
NativeRamBlock::free()
{
	if (storage != nullptr) {
		(void)storage->complete();
		storage->release();
		storage = nullptr;
	}
	IOBlockStorageDevice::free();
}

IOReturn
NativeRamBlock::reportBlockSize(UInt64 *value)
{
	if (value == nullptr) {
		return kIOReturnBadArgument;
	}
	*value = geometry.blockSize;
	return kIOReturnSuccess;
}

IOReturn
NativeRamBlock::reportMaxValidBlock(UInt64 *value)
{
	if (value == nullptr) {
		return kIOReturnBadArgument;
	}
	*value = geometry.blockCount == 0 ? 0 : geometry.blockCount - 1;
	return kIOReturnSuccess;
}

IOReturn
NativeRamBlock::reportEjectability(bool *value)
{
	if (value == nullptr) {
		return kIOReturnBadArgument;
	}
	*value = false;
	return kIOReturnSuccess;
}

IOReturn
NativeRamBlock::reportRemovability(bool *value)
{
	if (value == nullptr) {
		return kIOReturnBadArgument;
	}
	*value = false;
	return kIOReturnSuccess;
}

IOReturn
NativeRamBlock::reportWriteProtection(bool *value)
{
	if (value == nullptr) {
		return kIOReturnBadArgument;
	}
	*value = true;
	return kIOReturnSuccess;
}

IOReturn
NativeRamBlock::reportMediaState(bool *present, bool *changed)
{
	if (present == nullptr || changed == nullptr) {
		return kIOReturnBadArgument;
	}
	*present = ready;
	*changed = false;
	return kIOReturnSuccess;
}

IOReturn
NativeRamBlock::doAsyncReadWrite(IOMemoryDescriptor *buffer, UInt64 block, UInt64 count,
    IOStorageAttributes *attributes, IOStorageCompletion *completion)
{
	if (buffer == nullptr || completion == nullptr || count == 0) {
		return kIOReturnBadArgument;
	}
	if (block >= geometry.blockCount || count > geometry.blockCount - block) {
		native_ramblock_errors++;
		return kIOReturnBadArgument;
	}

	const uint64_t byteOffset = block * geometry.blockSize;
	const uint64_t requested = count * geometry.blockSize;
	uint64_t served = 0;

	if (buffer->getDirection() != kIODirectionIn) {
		// Read-only medium: refuse writes rather than silently dropping them.
		completion->action(completion->target, completion->parameter, kIOReturnUnsupported, 0);
		return kIOReturnUnsupported;
	}
	if (!read_within(geometry, byteOffset, requested, &served)) {
		native_ramblock_errors++;
		completion->action(completion->target, completion->parameter, kIOReturnBadArgument, 0);
		return kIOReturnBadArgument;
	}

	if (buffer->writeBytes(0, static_cast<char *>(storage->getBytesNoCopy()) + (vm_size_t)byteOffset,
	    (vm_size_t)served) != served) {
		native_ramblock_errors++;
		completion->action(completion->target, completion->parameter, kIOReturnIOError, 0);
		return kIOReturnIOError;
	}

	__atomic_fetch_add(&native_ramblock_reads, 1, __ATOMIC_RELAXED);
	completion->action(completion->target, completion->parameter, kIOReturnSuccess, served);
	return kIOReturnSuccess;
}


// Source-linked drivers in this port are not kexts: their Info.plist personalities are never consulted, so
// nothing matches them (docs/emulation/root-device-design.md). The display probe already solves this by
// being called from bsd_init.c; this is the same pattern. ci/ramblock-hook.py inserts the call, and the
// serial log lines below are what proves it ran.
extern "C" int
native_ramblock_publish(void)
{
	static int published = 0;

	if (published) {
		return published;
	}

	IOService *resources = IOService::getResourceService();
	if (resources == nullptr) {
		IOLog("NativeRamBlock: no resource service; not publishing\n");
		return 0;
	}

	NativeRamBlock *device = new NativeRamBlock;
	if (device == nullptr) {
		return 0;
	}
	if (!device->init()) {
		IOLog("NativeRamBlock: init failed\n");
		device->release();
		return 0;
	}

	// Attach to the resource service: it exists in every boot and gives IOBlockStorageDriver a place to
	// find the device, which is what the boot is waiting for.
	if (!device->attach(resources)) {
		IOLog("NativeRamBlock: attach failed\n");
		device->release();
		return 0;
	}
	if (!device->start(resources)) {
		IOLog("NativeRamBlock: start failed\n");
		device->detach(resources);
		device->release();
		return 0;
	}

	published = 1;
	IOLog("NativeRamBlock: published from the bsd_init hook\n");
	return published;
}
