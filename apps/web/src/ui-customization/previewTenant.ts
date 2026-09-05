/**
 * A preview fixture used to exercise the tenant layer while no tenancy exists.
 *
 * It is NOT a real association and NOT a real tenant: no record, no database
 * row, no isolation boundary. It disappears when Phase 2 introduces real
 * tenancy, and nothing may treat it as an account.
 */
export const PREVIEW_TENANT_ID = 'preview-tenant';
