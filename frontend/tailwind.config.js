/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        spotify: {
          green: '#F59E0B',
          'green-dark': '#D97706',
          black: '#121212',
          'dark-gray': '#181818',
          'mid-gray': '#282828',
          'light-gray': '#B3B3B3',
        },
      },
    },
  },
  plugins: [],
}
