// components/result-toast/result-toast.js
Component({
  properties: {
    visible: { type: Boolean, value: false },
    type: { type: String, value: 'success' },
    title: { type: String, value: '' },
    desc: { type: String, value: '' },
    time: { type: String, value: '' },
    duration: { type: Number, value: 1500 }
  },

  methods: {
    onTap: function () {
      this.triggerEvent('close')
    }
  }
})
