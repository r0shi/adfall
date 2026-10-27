import adapter from '@sveltejs/adapter-static';
export default {
  kit: {
    adapter: adapter({ pages: 'build', assets: 'build', fallback: 'index.html', precompress: false }),
    alias: { $data: '../web/data' },
    version: { pollInterval: 60_000 }   // notice a new build within a minute; the layout then makes the next navigation a full load
  }
};
