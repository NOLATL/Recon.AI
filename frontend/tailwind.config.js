/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bdo: {
          red: '#CC2529',
          'red-dark': '#A01E21',
          'red-light': '#E8393D',
          'red-glow': 'rgba(204,37,41,0.15)',
        },
        void: {
          DEFAULT: '#0A0A0A',
          surface: '#161616',
          elevated: '#1F1F1F',
          border: '#2A2A2A',
        },
        glass: {
          white: 'rgba(255,255,255,0.08)',
          'white-hover': 'rgba(255,255,255,0.12)',
          border: 'rgba(255,255,255,0.12)',
          'border-strong': 'rgba(255,255,255,0.20)',
        },
      },
      borderRadius: {
        liquid: '80px',
        'liquid-sm': '48px',
        pill: '9999px',
      },
      backdropBlur: {
        glass: '20px',
      },
      boxShadow: {
        glass: '0 8px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.08)',
        'glass-hover': '0 16px 48px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.12)',
        'red-glow': '0 0 24px rgba(204,37,41,0.3)',
        card: '0 2px 8px rgba(0,0,0,0.08)',
        'card-hover': '0 4px 16px rgba(0,0,0,0.12)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
