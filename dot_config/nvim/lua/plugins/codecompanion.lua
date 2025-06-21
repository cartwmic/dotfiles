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
      openai_personal = function()
        return require("codecompanion.adapters").extend("openai", {
          env = {
            api_key = "cmd:op read 'op://personal/OpenAI - key-1/credential' --no-newline",
          },
        })
      end,
      openai_work = function()
        return require("codecompanion.adapters").extend("openai", {
          env = {
            api_key = "cmd:op read 'op://personal/OpenAI - Axon - 2025-06-19/credential' --no-newline",
          },
        })
      end,
    },
    extensions = {
      mcphub = {
        callback = "mcphub.extensions.codecompanion",
        opts = {
          show_result_in_chat = true, -- Show mcp tool results in chat
          make_vars = true, -- Convert resources to #variables
          make_slash_commands = true, -- Add prompts as /slash commands
        },
      },
    },
  },
  dependencies = {
    "nvim-lua/plenary.nvim",
    "nvim-treesitter/nvim-treesitter",
    "ravitemer/mcphub.nvim",
  },
}
