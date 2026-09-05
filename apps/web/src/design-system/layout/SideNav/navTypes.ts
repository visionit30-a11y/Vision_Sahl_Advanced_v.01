import type { IconName } from '../../components/Icon/Icon';

export interface NavItem {
  id: string;
  /** Translation key resolved by the navigation namespace. */
  labelKey: string;
  icon: IconName;
  to: string;
  end?: boolean;
}

export interface NavSection {
  id: string;
  labelKey: string;
  items: NavItem[];
}
