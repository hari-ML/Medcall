/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Calm healthcare palette centred on teal #0F766E
        brand: {
          50: '#f0fdfa',
          100: '#ccfbf1',
          200: '#99f6e4',
          300: '#5eead4',
          400: '#2dd4bf',
          500: '#14b8a6',
          600: '#0d9488',
          700: '#0f766e',
          800: '#115e59',
          900: '#134e4a',
          DEFAULT: '#0f766e',
        },
      },
      fontFamily: {
        sans: [
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Noto Sans Tamil',
          'Noto Sans Devanagari',
          'sans-serif',
        ],
      },
      // Elderly-friendly baseline: 18px body text (overridable per element)
      fontSize: {
        body: ['1.125rem', { lineHeight: '1.75' }],
      },
      borderRadius: {
        card: '1rem',
      },
    },
  },
  plugins: [],
}
