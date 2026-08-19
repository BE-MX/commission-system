import WholesaleProtectedPage from "./protected-page";

export const dynamic = "force-dynamic";

export default function WholesaleHome() {
  return <WholesaleProtectedPage view="home" />;
}
