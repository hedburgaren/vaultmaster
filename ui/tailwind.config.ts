import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        vm: {
          bg: '#080c10',
          surface: '#0d1520',
          surface2: '#121e2e',
          surface3: '#182438',
          border: '#1e3350',
          'border-bright': '#2a4a6e',
          accent: '#00d4ff',
          accent2: '#ff6b35',
          accent3: '#39ff14',
          accent4: '#ffbe00',
          text: '#c8dff0',
          'text-dim': '#5a7a99',
          'text-bright': '#e8f4ff',
          danger: '#ff3355',
          success: '#00ff88',
          warning: '#ffbe00',
        },
      },
      fontFamily: {
        mono: ['Share Tech Mono', 'monospace'],
        display: ['Rajdhani', 'sans-serif'],
        code: ['Space Mono', 'monospace'],
      },
      animation: {
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'blink': 'blink 1s infinite',
        'shimmer': 'shimmer 2s infinite',
      },
      keyframes: {
        'pulse-glow': {
          '0%, 100%': { opacity: '1', boxShadow: '0 0 10px currentColor' },
          '50%': { opacity: '0.6', boxShadow: '0 0 4px currentColor' },
        },
        'blink': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        'shimmer': {
          '0%': { left: '-100%' },
          '100%': { left: '200%' },
        },
      },
    },
  },
  plugins: [],
}
export default config
