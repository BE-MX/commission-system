export type LocalAccountDefinition = {
  username: string;
  displayName: string;
  email: string;
  role: 'admin' | 'member';
};

export const LOCAL_ACCOUNTS: readonly LocalAccountDefinition[] = [
  { username: 'Design-LJC', displayName: 'Design-LJC', email: 'design-ljc@inventory.local', role: 'admin' },
  { username: 'Sales', displayName: 'Sales', email: 'sales@inventory.local', role: 'member' },
];
