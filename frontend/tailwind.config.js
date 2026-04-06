/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "#1a2332",
        border: "#2d3a4d",
        muted: "#8b9cb3",
      },
    },
  },
  plugins: [],
};
