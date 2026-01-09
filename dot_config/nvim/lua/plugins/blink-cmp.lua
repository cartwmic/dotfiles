return {
  {
    "saghen/blink.cmp",
    dependencies = { "milanglacier/minuet-ai.nvim" },
    opts = {
      -- Add minuet source and keybinding
      keymap = {
        preset = "default",
        ["<CR>"] = { "accept", "fallback" },
        ["<A-y>"] = {
          function(cmp)
            cmp.show({ providers = { "minuet" } })
          end,
        },
      },
      sources = {
        -- Add minuet to default sources for auto-complete
        default = { "lsp", "path", "snippets", "buffer", "minuet" },
        providers = {
          minuet = {
            name = "minuet",
            module = "minuet.blink",
            score_offset = 100,
          },
        },
      },
    },
  },
}
