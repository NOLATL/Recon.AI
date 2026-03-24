/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bdo: {
          red: '#98002E',
          'red-dark': '#7A0025',
          'red-light': '#BE1B48',
          'red-glow': 'rgba(152,0,46,0.15)',
        },
        void: {
          DEFAULT: '#E7E7E7',
          surface: '#333333',
          elevated: '#444444',
          border: '#404040',
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
        'red-glow': '0 0 24px rgba(152,0,46,0.3)',
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
