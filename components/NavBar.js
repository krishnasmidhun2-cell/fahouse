import Link from 'next/link';

// Simple navigation bar for the app.
export default function NavBar() {
  return (
    <nav className="nav">
      <Link href="/">Dashboard</Link>
      <Link href="/add-cycle">Add Cycle</Link>
      <Link href="/graphs">Graphs</Link>
    </nav>
  );
}
