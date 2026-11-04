// Large JSON fixtures are imported without type inference (resolveJsonModule is off on purpose: inferring a
// ~1 MB literal type slows the type checker). fixtures.ts casts the value to MockFixtures, built from DTO types.
declare module "*.json" {
  const value: unknown;
  export default value;
}
