import { createRoot } from 'react-dom/client';
import { createBridge } from './bridge';
import { LeftNav } from './components/LeftNav';
import { Header } from './components/Header';

// Initialize bridge on window
window.ClawWeb = createBridge();

// Mount LeftNav
const navRoot = document.getElementById('react-left-nav');
if (navRoot) {
  createRoot(navRoot).render(<LeftNav />);
}

// Mount Header
const headerRoot = document.getElementById('react-header');
if (headerRoot) {
  createRoot(headerRoot).render(<Header />);
}
