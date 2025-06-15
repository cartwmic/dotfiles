return {
  "olimorris/codecompanion.nvim",
  opts = {
    strategies = {
      chat = {
        adapter = "anthropic",
      },
      inline = {
        adapter = "anthropic",
      },
    },
    adapters = {
      anthropic = function()
        return require("codecompanion.adapters").extend("anthropic", {
          env = {
            api_key = "cmd:op read 'op://personal/Anthropic - key-1/credential' --no-newline",
          },
        })
      end,
      openai = function()
        return require("codecompanion.adapters").extend("openai", {
          env = {
            api_key = "cmd:op read 'op://personal/OpenAI - key-1/credential' --no-newline",
          },
        })
      end,
    },
  },
  dependencies = {
    "nvim-lua/plenary.nvim",
    "nvim-treesitter/nvim-treesitter",
  },
}
