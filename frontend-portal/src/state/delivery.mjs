export const deliveryFields = [
  ['contact_name', 'Contact name', 'name', 100, false], ['phone', 'Phone number', 'tel', 40, false],
  ['address_line1', 'Address line 1', 'address-line1', 200, false], ['address_line2', 'Address line 2 (optional)', 'address-line2', 200, false],
  ['city', 'City', 'address-level2', 100, false], ['region', 'State / region', 'address-level1', 100, false],
  ['postal_code', 'Postal code', 'postal-code', 32, false], ['country_code', 'Country code (e.g. US, GB)', 'country', 2, false],
]
export const emptyDelivery = () => Object.fromEntries(deliveryFields.map(([key]) => [key, '']))
