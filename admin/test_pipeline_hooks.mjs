// Hook de resolución (node:module register): SOLO cuando pipeline.js importa ../api.js, ../router.js
// o ../store.js se sustituyen por stubs. El resto (pipeline-actions.js, pipeline-render.js) es el real.
const STUBS = {
  '../api.js': new URL('./test_pipeline_stubs/api.mjs', import.meta.url).href,
  '../router.js': new URL('./test_pipeline_stubs/router.mjs', import.meta.url).href,
  '../store.js': new URL('./test_pipeline_stubs/store.mjs', import.meta.url).href,
};

export async function resolve(specifier, context, nextResolve) {
  if (context.parentURL && context.parentURL.endsWith('/pages/pipeline.js') && STUBS[specifier]) {
    return { url: STUBS[specifier], shortCircuit: true };
  }
  return nextResolve(specifier, context);
}
