export default {
  root: "..",
  test: {
    include: ["mcp/tests/**/*.test.ts"],
    coverage: {
      include: ["mcp/src/index.ts", "web/app.js"],
      reporter: ["text", "lcov"],
      reportsDirectory: "mcp/coverage",
    },
  },
};
