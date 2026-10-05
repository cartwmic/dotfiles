-- Browser-like Markdown view inside Neovim: an 80-column rendered buffer with
-- tables, callouts, images and Mermaid. In a plain kitty window (>= 0.40)
-- headings are drawn larger with kitty's text sizing protocol; elsewhere
-- (for example inside Herdr) they fall back to normal size. The rendered view
-- is a separate read-only buffer; edit in the source. passage-review reviews
-- also accept <leader>zc comments in the rendered view.
return {
  {
    "delphinus/md-render.nvim",
    version = "*",
    cmd = "MdRender",
    keys = {
      -- Global, not ft-scoped: md-render sets up its rendered buffer with
      -- autocmds suppressed, so a FileType-scoped key never reaches it.
      {
        "<leader>mr",
        function()
          if vim.b.md_render or vim.bo.filetype == "markdown" then
            require("md-render").preview.toggle()
          end
        end,
        desc = "Markdown: toggle rendered view",
      },
      { "<leader>ms", "<cmd>vertical MdRender split<cr>", ft = "markdown", desc = "Markdown: source + rendered split" },
      { "<leader>ma", "<cmd>MdRender auto toggle<cr>", ft = "markdown", desc = "Markdown: render outside Insert" },
      { "<leader>mf", "<Plug>(md-render-preview)", ft = "markdown", desc = "Markdown: floating preview" },
    },
  },
  {
    "folke/which-key.nvim",
    optional = true,
    opts = { spec = { { "<leader>m", group = "markdown" } } },
  },
}
