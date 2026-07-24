import { withMermaid } from 'vitepress-plugin-mermaid'

export default withMermaid({
  lang: 'zh-CN',
  title: 'CodeRushOJ',
  description: '可部署、可扩展、可验证的开源在线评测系统',
  srcExclude: ['superpowers/**'],
  cleanUrls: true,
  lastUpdated: process.env.CODERUSHOJ_DOCS_LAST_UPDATED !== 'false',
  head: [
    ['meta', { name: 'theme-color', content: '#5b5bd6' }],
    ['meta', { name: 'color-scheme', content: 'light dark' }]
  ],
  themeConfig: {
    siteTitle: 'CodeRushOJ',
    nav: [
      { text: '快速开始', link: '/guide/quickstart' },
      { text: '架构', link: '/architecture/platform' },
      { text: '运维', link: '/operations/troubleshooting' },
      { text: '发版', link: '/releases/' }
    ],
    sidebar: [
      {
        text: '开始使用',
        items: [
          { text: '平台概览', link: '/' },
          { text: '安装与部署', link: '/guide/quickstart' }
        ]
      },
      {
        text: '工程设计',
        items: [
          { text: '平台架构', link: '/architecture/platform' },
          { text: '项目历史', link: '/project/history' },
          { text: '里程碑与 Issue', link: '/project/milestones' },
          { text: '发版流程', link: '/project/release-process' }
        ]
      },
      {
        text: '运维手册',
        items: [
          { text: '故障排查', link: '/operations/troubleshooting' },
          { text: '备份与恢复', link: '/operations/backup-restore' }
        ]
      },
      {
        text: '发布',
        items: [{ text: '版本与变更', link: '/releases/' }]
      }
    ],
    socialLinks: [{ icon: 'github', link: 'https://github.com/orgs/CodeRushOJ/repositories' }],
    search: { provider: 'local' },
    footer: {
      message: 'Apache-2.0 · Built for reproducible judging',
      copyright: 'CodeRushOJ contributors'
    },
    editLink: {
      pattern: 'https://github.com/CodeRushOJ/croj-platform/edit/main/docs/:path',
      text: '在 GitHub 上编辑此页'
    }
  },
  mermaid: {
    theme: 'neutral',
    securityLevel: 'strict'
  }
})
