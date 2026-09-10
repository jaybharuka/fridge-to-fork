import { StaticPage } from '@/components/shared/StaticPage';

export default function NotFound() {
  return (
    <StaticPage title="Page not found" lead="This page doesn't exist, but your next meal still can.">
      <p>The link you followed might be broken, or the page may have moved.</p>
    </StaticPage>
  );
}
