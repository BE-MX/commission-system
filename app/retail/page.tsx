import RetailProtectedPage from "./protected-page";

export const dynamic = "force-dynamic";

export default function RetailHome() {
  return <RetailProtectedPage view="home" />;
}
