      subroutine init 
c--
c--   subroutine inti.f is designed to initialize all the necessary
c--   data and arrays
c--
      use muc_mod
c  --						        
c  -- *****************************
c  --  Array Initialization
c  -- *****************************
c  -- Initialize the statistics varables
      GuiTotalTime = 0.0
      MaxMove=0

      vehicle_length=21.12
! End
	if (iteration.lt.1) then
        jtotal = 0

      	jj=0
	endif
!	jj=0


	jj_MUC = 0
      jj_i=0
      multi=0
      listtotal=0
      maxden=250
      entrymx=2000.0 ! /hr/lane
      int_d=10
      iso_ok=0
      iue_ok=0

	
	ienroute_ok=0


      itag0=0
      itag1=0
      itag2=0
      itag3=0
      information=0
      information_1=0
      information_2=0
      information_3=0
      noinformation=0
      noinformation_1=0
      noinformation_2=0
      noinformation_3=0
      dtotal1=0.0
      dtotal2=0.0
      dtotal2_1=0.0
      dtotal2_2=0.0
      dtotal2_3=0.0
      dtotal3=0.0
      dtotal3_1=0.0
      dtotal3_2=0.0
      dtotal3_3=0.0
      vtothr1=0
      vtothr2=0
      vtothr2_1=0
      vtothr2_2=0
      vtothr2_3=0
      vtothr3=0
      vtothr3_1=0
      vtothr3_2=0
      vtothr3_3=0
      triptime1=0
      triptime2=0
      triptime2_1=0
      triptime2_2=0
      triptime2_3=0
      triptime3=0
      triptime3_1=0
      triptime3_2=0
      triptime3_3=0
      ave_trip1=0
      ave_trip2=0
      ave_trip2_1=0
      ave_trip2_2=0
      ave_trip2_3=0
      ave_trip3=0
      ave_trip3_1=0
      ave_trip3_2=0
      ave_trip3_3=0
      stoptime=0
      stopinfo=0
      stopinfo_1=0
      stopinfo_2=0
      stopinfo_3=0
      stopnoinfo=0
      stopnoinfo_1=0
      stopnoinfo_2=0
      stopnoinfo_3=0
      avestoptime=0
      avestopinfo=0
      avestopinfo_1=0
      avestopinfo_2=0
      avestopinfo_3=0
      avestopnoinfo=0
      avestopnoinfo_1=0
      avestopnoinfo_2=0
      avestopnoinfo_3=0
      entry_queue1=0
      entry_queue2=0
      entry_queue2_1=0
      entry_queue2_2=0
      entry_queue2_3=0
      entry_queue3=0
      entry_queue3_1=0
      entry_queue3_2=0
      entry_queue3_3=0
      ave_entry1=0
      ave_entry2=0
      ave_entry2_1=0
      ave_entry2_2=0
      ave_entry2_3=0
      ave_entry3=0
      ave_entry3_1=0
      ave_entry3_2=0
      ave_entry3_3=0
      avedtotal1=0
      avedtotal2=0
      avedtotal2_1=0
      avedtotal2_2=0
      avedtotal2_3=0
      avedtotal3=0
      avedtotal3_1=0
      avedtotal3_2=0
      avedtotal3_3=0
      totaldecsion=0
      totalswitch=0
      nout_tag=0
      nout_nontag=0
      nout_tag_i=0
      nout_nontag_i=0
      vavg1=0
      vavg2=0
      vavg2_1=0
      vavg2_2=0
      vavg2_3=0
      vavg3=0
      vavg3_1=0
      vavg3_2=0
      vavg3_3=0
      tt=0.0
      ttt=0.0

      soda2=0
      t=0.0
      time_now=0.0
      isigcount=1
      ipint=1
      numcars=0
      oldnumcars=0
      nubus=0
      vms_num=0
      inci_num=0
      jrestore = 1
      maxintervals=1

      int=0

      nout_tag=0
      nout_nontag=0
      oldnumcars=0

      IF(ALLOCATED(ForToBackLink))THEN
      ForToBackLink(:)=0
      ENDIF
      IF(ALLOCATED(TTimeOfBackLink))THEN
      TTimeOfBackLink(:)=0
      ENDIF
      IF(ALLOCATED(iunod))THEN
      iunod(:)=0
      ENDIF
      IF(ALLOCATED(UNodeOfBackLink))THEN
      UNodeOfBackLink(:)=0
      ENDIF
      IF(ALLOCATED(move))THEN
      move(:,:)=0
      ENDIF
      IF(ALLOCATED(movein))THEN
      movein(:,:)=0
      ENDIF
      IF(ALLOCATED(penalty))THEN
      penalty(:,:)=0
      ENDIF
C      IF(ALLOCATED(almov))THEN
      almov(:,:)=0
C      ENDIF
      IF(ALLOCATED(nodenum))THEN
      nodenum(:)=0
      ENDIF
C      IF(ALLOCATED(cma))THEN
      cma(:)=0
C      ENDIF
C      IF(ALLOCATED(cmalink))THEN
      cmalink(:)=0
C      ENDIF
      IF(ALLOCATED(destination))THEN
      destination(:)=0
      ENDIF

      IF(ALLOCATED(MasterDest))THEN
      MasterDest(:)=0
      ENDIF
C      IF(ALLOCATED(leftcapWb))THEN
      leftcapWb(:,:,:)=0
C      ENDIF
C      IF(ALLOCATED(leftcapWOb))THEN
      leftcapWOb(:,:,:,:)=0
C      ENDIF
C      IF(ALLOCATED(classpro))THEN
      classpro(:)=0
C      ENDIF
C      IF(ALLOCATED(classpro2))THEN
      classpro2(:)=0
C      ENDIF
C      IF(ALLOCATED(nodetmp))THEN
      nodetmp(:)=0
C      ENDIF
      IF(ALLOCATED(llink))THEN
      llink(:,:)=0
      ENDIF
      IF(ALLOCATED(inlink))THEN
      inlink(:,:)=0
      ENDIF 

      price_regular=0.0
      price_hot_lov=0.0
      price_hot_hov=0.0
      iactual_lov_hot=0
      iactual_hov_hot=0
      iactual_lov_ohot=0
      iactual_hov_ohot=0
      time_lov_hot=0.0
      time_hov_hot=0.0
      time_lov_ohot=0.0
      time_hov_ohot=0.0
      link_hot=0
      link_hov=0
      naout_ah=0
      mmtt=0
      ktotal_out=0
      CntDemTime = 0
      SignCount = 0

      return
      end
