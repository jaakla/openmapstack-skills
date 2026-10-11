import fs from "node:fs";
const metadata = JSON.parse(fs.readFileSync(new URL("./metadata.json", import.meta.url)));
export default {
  title: "OpenMapStack · Observable",
  root: "src",
  output: "dist",
  style: "style.css",
  sidebar: false,
  toc: false,
  pager: false,
  search: false,
  globalStylesheets: [],
  head: `<script id="openmapstack-view" type="application/json">${JSON.stringify(metadata).replaceAll("<", "\\u003c")}</script>`,
  footer: 'Built with <a href="https://observablehq.github.io/framework/">Observable Framework</a> · <a href="https://github.com/jaakla/openmapstack-skills/tree/main/examples/observable-cities">Sample source</a>'
};
