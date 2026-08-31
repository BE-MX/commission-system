export async function saveRouteConfiguration({ save, reload }) {
  await save()
  await reload()
}
