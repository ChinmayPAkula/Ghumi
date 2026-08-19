/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Ghumi_Design_Spec_v3/v4 §1 — unified color system.
        // These are the ONLY colors this project uses. Don't add ad-hoc
        // hex values in components — extend this list instead.
        paper: '#F6F4EF',
        ink: '#16241F',
        brand: '#1F5C4A',
        dusk: '#16332B',
        brass: '#C98A3B',
        route: '#A83E32',
        line: '#D8D3C4',
        muted: '#6B7570',
      },
      fontFamily: {
        display: ['Fraunces', 'serif'],
        body: ['"General Sans"', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
}
