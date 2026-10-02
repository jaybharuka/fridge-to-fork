// What the header's account menu shows. Pure (no React) so it is unit tested in plain Node: see accountMenu.test.ts.

export interface AccountMenuModel {
  /** The status line at the top: green when connected, muted otherwise. */
  statusLabel: string;
  connected: boolean;
  /** The two order-history rows: only for a connected account, and Food only while Food ordering is switched on. */
  showInstamartOrders: boolean;
  showFoodOrders: boolean;
}

export function accountMenuModel(connected: boolean, foodOrderingEnabled: boolean): AccountMenuModel {
  return {
    statusLabel: connected ? 'Connected to Swiggy' : 'Not connected',
    connected,
    showInstamartOrders: connected,
    showFoodOrders: connected && foodOrderingEnabled,
  };
}
