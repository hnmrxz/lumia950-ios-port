/* Weak stand-ins for the two provider symbols the bootstrap pass references.
 *
 * The pass exists only to leave compile records, and it runs before any builder has produced
 * the archives that define these; a weak definition lets that link finish while the real
 * (strong) definitions still win in the final link. Neither function is ever called in the
 * bootstrap image.
 */
typedef int kern_return_t;

__attribute__((weak)) kern_return_t
corecrypto_kext_start(void *info, void *data)
{
	(void)info;
	(void)data;
	return 1; /* KERN_FAILURE: nothing in this image calls it */
}

__attribute__((weak)) int
native_legacy_display_probe(void *provider)
{
	(void)provider;
	return 0;
}
