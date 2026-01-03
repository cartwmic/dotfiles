return {
  "Davidyz/VectorCode",
  build = "uv tool upgrade vectorcode", -- This helps keeping the CLI up-to-date
  dependencies = { "nvim-lua/plenary.nvim" },
  cmd = "VectorCode", -- if you're lazy-loading VectorCode
}
