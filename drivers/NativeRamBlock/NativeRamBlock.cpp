// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// NativeRamBlock: a synthetic IOMedia so `vfs_mountroot` has something to mount.
//
// The guarded run returns from BSD initialisation and then waits for an IOMedia whose content is
// Apple_HFS (docs/emulation/2026-11-25-bsd-init-crossed.md). No storage path exists that can answer
// that on this port yet, so this driver provides the smallest possible one: a contiguous buffer, the
// HFS content hint, and read/write served straight out of the buffer. It exists to move the VFS rung
// forward, not to ship (docs/emulation/root-device-design.md).
//
// It has no MMIO, no clock, no power domain and no interrupt, so there is nothing about it that needs
// real hardware to prove. What it does carry is the IOStorageFamily dependency, which `board.toml`
// documents as resolvable only after the prelink merge -- same constraint as NativeSdhci.

#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/storage/IOMedia.h>
#include <pexpert/pexpert.h>

#include "NativeRamBlock.h"
#include "RamBlockCore.h"

using namespace native_ram_block;

OSDefineMetaClassAndStructors(NativeRamBlock, IOMedia)

extern "C" {
// Visible in the kernel symbol table so a boot with no console still says whether the media appeared.
volatile uint32_t native_ramblock_ready = 0;
volatile uint64_t native_ramblock_bytes = 0;
volatile uint64_t native_ramblock_reads = 0;
volatile uint64_t native_ramblock_writes = 0;
volatile uint64_t native_ramblock_errors = 0;
}

bool
NativeRamBlock::start(IOService *provider)
{
	if (!OSDynamicCast(IOMedia, this)) {
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

	buffer = IOMallocContiguous((vm_size_t)geometry.bytes, PAGE_SIZE, nullptr);
	if (buffer == nullptr) {
		native_ramblock_errors++;
		return false;
	}
	bzero(buffer, (vm_size_t)geometry.bytes);

	// Whole media, 512-byte blocks, content Apple_HFS: this is exactly the match vfs_mountroot asks for.
	if (!init(0, geometry.bytes, geometry.blockSize, true, kContentHint)) {
		IOFreeContiguous(buffer, (vm_size_t)geometry.bytes);
		buffer = nullptr;
		native_ramblock_errors++;
		return false;
	}

	setProperty(kIOMediaContentKey, kContentHint);
	setProperty(kIOMediaWholeKey, kOSBooleanTrue);
	setProperty("NativeRamBlockGeometry", (unsigned long long)geometry.bytes, 64);
	registerService();

	native_ramblock_bytes = geometry.bytes;
	native_ramblock_ready = 1;
	return true;
}

void
NativeRamBlock::stop(IOService *provider)
{
	if (buffer != nullptr) {
		IOFreeContiguous(buffer, (vm_size_t)geometry.bytes);
		buffer = nullptr;
	}
	native_ramblock_ready = 0;
	IOMedia::stop(provider);
}

void
NativeRamBlock::free()
{
	if (buffer != nullptr) {
		IOFreeContiguous(buffer, (vm_size_t)geometry.bytes);
		buffer = nullptr;
	}
	IOMedia::free();
}

void
NativeRamBlock::read(IOService *client, UInt64 byteOffset, IOMemoryDescriptor *bufferDescriptor,
    IOStorageCompletion completion)
{
	uint64_t served = 0;
	if (bufferDescriptor == nullptr || !read_within(geometry, byteOffset, bufferDescriptor->getLength(), &served)) {
		native_ramblock_errors++;
		complete(completion, kIOReturnBadArgument, 0);
		return;
	}
	// Serving from the head of the buffer: there is nothing in it to be wrong about yet, and the point of
	// this rung is that the read path exists and reports the bytes it moved.
	(void)bufferDescriptor->writeBytes(0, buffer, (vm_size_t)served);
	native_ramblock_reads++;
	complete(completion, kIOReturnSuccess, (IOByteCount)served);
}

void
NativeRamBlock::write(IOService *client, UInt64 byteOffset, IOMemoryDescriptor *bufferDescriptor,
    IOStorageCompletion completion)
{
	if (bufferDescriptor == nullptr ||
	    !write_within(geometry, byteOffset, bufferDescriptor->getLength())) {
		native_ramblock_errors++;
		complete(completion, kIOReturnBadArgument, 0);
		return;
	}
	(void)bufferDescriptor->readBytes(0, buffer + (vm_size_t)byteOffset,
	    (vm_size_t)bufferDescriptor->getLength());
	native_ramblock_writes++;
	complete(completion, kIOReturnSuccess, (IOByteCount)bufferDescriptor->getLength());
}
