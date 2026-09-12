export default  {
      title: 'Cost Strategy',
      description:
        'Maintain max cost per request, billing mode, and upgrade threshold for each tier. Belongs to the billing operations domain.',
      stats: {
        total: 'Total policies',
        byToken: 'Per Token',
        byRequest: 'Per Request',
        byCredit: 'Per Credit',
      },
      columns: {
        policyName: 'Policy name',
        modelTier: 'Model tier',
        maxCostPerRequest: 'Max cost / request',
        billingMode: 'Billing mode',
        upgradeThreshold: 'Upgrade threshold',
        actions: 'Actions',
      },
      actions: {
        create: 'New Cost Policy',
        edit: 'Edit',
      },
      billingModes: {
        token: 'Per Token',
        request: 'Per Request',
        credit: 'Per Credit',
      },
      empty: 'No cost policies',
      modal: {
        editTitle: 'Edit Cost Policy',
        placeholders: {
          policyName: 'e.g. default',
          price: '0.000000',
        },
      },
      messages: {
        loadFailed: 'Failed to load cost policies',
        created: 'Cost policy created',
        updated: 'Cost policy updated',
        createFailed: 'Failed to create cost policy',
        updateFailed: 'Failed to update cost policy',
      },
    }
