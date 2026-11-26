// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// The kmod entry points a kext bundle needs.
//
// A kext executable is not just a Mach-O with a personality: the loader looks for the module's own record and its
// start/stop routines (MH_KEXT_BUNDLE carries them in the __kmod segment / __kmod_* sections). The personality in
// Info.plist only decides which platform device the driver is offered; this file is what makes the bundle loadable at
// all, and it is why the archive that goes into the kernel and the kext that goes into an mkext cannot be the same
// artefact.
//
// The start routine deliberately does nothing but report success: IOService matching does the work once the
// personality is in the catalogue.

#include <mach/kmod.h>
#include <libkern/OSReturn.h>

extern "C" kern_return_t NativeSdhciKextStart(kmod_info_t *info, void *data);
extern "C" kern_return_t NativeSdhciKextStop(kmod_info_t *info, void *data);

extern "C" kern_return_t
NativeSdhciKextStart(kmod_info_t *info, void *data)
{
    (void)info;
    (void)data;
    return KERN_SUCCESS;
}

extern "C" kern_return_t
NativeSdhciKextStop(kmod_info_t *info, void *data)
{
    (void)info;
    (void)data;
    return KERN_SUCCESS;
}

KMOD_EXPLICIT_DECL(org.unixnu.NativeSdhci, "0.1.0", NativeSdhciKextStart, NativeSdhciKextStop)
