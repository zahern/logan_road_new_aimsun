      subroutine input
c --
c -- This subroutine reads all the input files.  ConnectorToOriginFlag
c --
c -- This subroutine is called from main 
c -- This subroutine calls read_signals and prepare_network 
c --
c -- INPUT :
c --   All input data  files for DYNASMART (fort.41 -fort.50)
c --
c -- OUTPUT :
c -- no specific output 
c --
      use muc_mod
      use vector_mod
c --
      real demandsum,demandsumT,demandsumH,LWTmp,YLevel2N,YMove2N
      integer OrigZone,alexnzones,error,j,vmaxtp,sattp,mfrtp
      integer ConZoneTmp(100)
      integer::i11=0
      integer::iseed(1)=0 ! One seed
      real::OrigVehFrac(6)=0 ! original vehicle type fractions as entered in scenario.dat
      integer::buspathtmp(1000)=0
      integer::busstoptmp(1000)=0
      integer::busvalue
      logical::CState
      real,allocatable::demtmp(:)
      integer::FSize=0
      character *1 reply
      logical::Fexist=.False.
      logical::Lenpnt=.False.
      logical::Grdpnt=.False.    
      integer FNodetmp,TNodetmp,Veh_Type_Tmp,Dem_Mode_Tmp,MUC_Mode_Tmp
      character *20 ErString
      integer,allocatable::mmzonetmp(:)
c      integer,allocatable::ConnectorToOriginFlag(:)
	real MUC_Frac_Tmp(5),MUC_Frac_Sum,Dem_Frac_Sum 
c
c -- fort.41 (network.dat) network data
c --
c -- nzones : number of zones in the network.
c -- noofnodes : number of nodes in the network.
c -- noofarcs : number of links in the network.
c --
c        if (EOF(41)) then
c	 ErString = "network.dat"
c	 call ErReadEOF(ErString)
c	endif
      read(41,*,iostat=error) nzones,noofnodes,noofarcs,kay,
     +                        SuperZoneSwitch
c	print *,'Alex01',nzones
c	alexnzones=nzones
c Kay is zero in network.dat
      if(kay.eq.0)then
	write(911,*) 'INPUT ERROR: '
	write(911,*) 'The number of shortest paths to be solved must be'
	write(911,*) 'at least 1. Check the first record, fourth field'
	write(911,*) 'in network.dat input file'
	stop
      endif
c	print *,'Alex02',nzones
c Zone Aggregation Flag is neither zero or one in network.dat
      if(SuperZoneSwitch.lt.0.or.SuperZoneSwitch.gt.1)then
	write(911,*) 'INPUT ERROR: '
	write(911,*) 'The Super Zone Aggregation Flag must be either'
	write(911,*) '0 or 1. Check the first record, fifth field'
	write(911,*) 'in network.dat input file'
	stop
      endif
c	print *,'Alex03',nzones
C	IF(realdm.eq.0)THEN
c
C      if(EOF(42)) then
C	 ErString = "demand.dat"
C	 call ErReadEOF(ErString)
C	endif
      read(42,*,iostat=error) nints,multi
C      if(EOF(54)) then
C	 ErString = "demand_truck.dat"
C	 call ErReadEOF(ErString)
C	endif
      read(54,*,iostat=error) nintsT,multiT
C      if(EOF(61)) then
C	 ErString = "demand_HOV.dat"
C	 call ErReadEOF(ErString)
C	endif
      read(61,*,iostat=error) nintsH,multiH
C      if(EOF(44)) then
C	 ErString = "control.dat"
C	 call ErReadEOF(ErString)
C	endif
C	ENDIF
c	
	read(44,*,iostat=error) isig
C      if(EOF(45)) then
C	 ErString = "ramp.dat"
C	 call ErReadEOF(ErString)
C	endif
	read(45,*,iostat=error) dec_num,nrate
C      if(EOF(46)) then
C	 ErString = "incident.dat"
C	 call ErReadEOF(ErString)
C	endif
      read(46,*,iostat=error) inci_num
C      if(EOF(49)) then
C	 ErString = "vms.dat"
C	 call ErReadEOF(ErString)
C	endif
	read(49,*,iostat=error) vms_num
C      if(EOF(50)) then
C	 ErString = "bus.dat"
C	 call ErReadEOF(ErString)
C	endif
	read(50,*,iostat=error) nubus
c	Print *,'Alexbus',nubus
C      if(EOF(55)) then
C	 ErString = "TrafficFlowModel.dat"
C	 call ErReadEOF(ErString)
C	endif
      read(55,*,iostat=error) NoOfFlowModel
C      if(EOF(56)) then
C	 ErString = "StopCap4Way.dat"
C	 call ErReadEOF(ErString)
C	endif
      read(56,*,iostat=error) NLevel,NMove
C      if(EOF(57)) then
C	 ErString = "StopCap2Way.dat"
C	 call ErReadEOF(ErString)
C	endif
	read(57,*,iostat=error) Level2N,Move2N
C      if(EOF(58)) then
C	 ErString = "WorkZone.dat"
C	 call ErReadEOF(ErString)
C	endif
	read(58,*,iostat=error) WorkZoneNum
C      if(EOF(59)) then
C	 ErString = "GradeLenghPCE.dat"
C	 call ErReadEOF(ErString)
C	endif
      read(59,*,iostat=error) GradeNum,LenNum,TruckNum
C      if(EOF(60)) then
C	 ErString = "YieldCap.dat"
C	 call ErReadEOF(ErString)
C	endif
	read(60,*,iostat=error) YLevel2N,YMove2N
c*******************************************************************
c      if(realdm.eq.2)then
C        if(EOF(550)) then
C  	  write(911,*) 'The file path.dat is missing'
C        write(911,*) 'Provide the file or rename output_path.dat'
C        write(911,*) 'to path.dat if using a previous run'
C	  stop
C	  endif
c	endif
c*******************************************************************
c	print *,'Alex012',nzones,nubus
	if(realdm.ne.1)then
C        if(EOF(500)) then
c	!    ErString = "vehicle.dat"
c	!    call ErReadEOF(ErString)
c	!  endif
c  ***********************************************************
C	  write(911,*) 'The file vehicle.dat is missing'
C        write(911,*) 'Provide the file or rename output_vehicle.dat'
C        write(911,*) 'to vehicle.dat if using a previous run'
C	  stop
C	  endif
c  ***********************************************************
      read(500,*,iostat=error) MaxVehicles,noofstops
	
c	print *, MaxVehicles,noofstops 
c	read(500,*,iostat=error) !skip a line
	if(noofstops.gt.1.and.realdm.eq.2)then
      write(911,*) 'This version doesnt allow loading trip' 
      write(911,*) 'chain with path. Please change setting'
	stop
	endif
	LoadTripChain=0
      endif
c	print *,'Alex04',nzones	
      if((realdm.eq.1.and.multi.eq.0.and.nubus.eq.0).or.
     *(realdm.ne.1.and.MaxVehicles.lt.1.and.nubus.lt.1))then
	write(911,*) 'INPUT ERROR : '
	write(911,*) 'Total number of vehicles to be loaded is zero'
	write(911,*) 'Please check the following files depending on'
	write(911,*) 'the demand generation mode'
	write(911,*) 'demand.dat'
	write(911,*) 'vehicle.dat'
	write(911,*) 'bus.dat'
	stop
      endif
	nu_switch=1000
c********************************************************
	if(realdm.eq.2)then 
	read(550,*) xxx
	rewind(550)
C	if((EOF(550)).and.xxx.eq.0) then
C	write(911,*) 'no paths are specified in path.dat'
C	   else
      if(xxx.eq.0)then
      write(911,*) 'Error in reading path.dat'
	write(911,*) 'Check format of path.dat'
	stop
	endif
	endif
c*****************************************************
c --  call allocate_dyna to allocate memory for all dynasmart arrays
      if(SuperZoneSwitch.eq.0)then
	noof_master_destinations=nzones
	noof_master_destinations_original=nzones
	else
	open(file='SuperZone.dat',unit=913,status='old')
C       if(EOF(913)) then
C	  ErString = "SuperZone.dat"
C	  call ErReadEOF(ErString)
C	 endif
      read(913,*,iostat=error) noof_master_destinations
	noof_master_destinations_original=noof_master_destinations
      endif
      noofarcs_org=noofarcs
      noofnodes_org=noofnodes
c      print *, 'Alex210',nzones,nubus
      call allocate_dyna
c --
c -- Read the master destination (zone centroid) for each zone
	if(SuperZoneSwitch.eq.1)then
C       if(EOF(913)) then
C	  ErString = "SuperZone.dat"
C	  call ErReadEOF(ErString)
C	 endif
      read(913,*,iostat=error)
	read(913,*) (OrigZone,i=1,nzones) ! this reading just for skipping
      read(913,*,iostat=error)
	read(913,*,iostat=error) (MasterDest(i),i=1,nzones)
	close(913)
	else
      do i=1,nzones
	MasterDest(i)=i
      enddo
	endif
      do mm=1,nzones
   	if(MasterDest(mm).gt.noof_master_destinations)then
	write(911,*)"Error in network.dat"
	write(911,*)"Check the destination settings for zone",mm   
	stop
      endif
	enddo
 	destination(:)=0
c --
c -- fort.43 (scenario.dat) the scenario data information
c --
c -- ribfa : relative indifference band (percent improvement at whcih 
c --         a user will switch his/her path).
c -- bound : threshold bound for path switching (user will not switch path
c --         unless the time savings are greater than the bound)
c -- ipinit : an index for initial path assignment
c --  if =0, randomly select from the k shortest path
c --  if =1, assign the generated vehicles to the best path (out of k) 
c -- 
C      if(EOF(43)) then
C	  ErString = "scenario.dat"
C	  call ErReadEOF(ErString)
C	endif
      read(43,*,iostat=error) ribfa,bound,istrm,ipinit,InfoPM
      if(ipinit.lt.0.or.ipinit.gt.1)then
      write(911,*) 'INPUT ERROR : scenario data file'
      write(911,*) 'Path index is out of the possible range'
      write(911,*) 'the value should be either 0 or 1'
      stop
      endif
      if(InfoPM.lt.0.or.InfoPM.gt.1)then
      write(911,*) 'INPUT ERROR : scenario data file'
      write(911,*) 'VMS preemption mode is out of the possible range'
      write(911,*) 'the value should be either 0 or 1'
      stop
      endif
c one-seed implementation
c      print *, 'Alex220',nzones,nubus
	if(istrm.ne.0)then
	iseed(1)=istrm
c	call random_seed()
	print *, iseed
C	pause
C	call random_seed(PUT=iseed)			! Alex: temporaly disable because of problems with PUT . . .
	else
	call random_seed()
	endif
c	print *, 'Alex230',nzones,nubus
c --
c -- com_frac : fraction of compliant vehicles
c --
      read(43,*,iostat=error) com_frac
c --
c -- Check for input errors
c --  
      if(com_frac.lt.0.or.com_frac.gt.1)then
      write(911,*) 'INPUT ERROR : scenario data file'
      write(911,*) 'com_frac is out of the possible range'
      write(911,*) 'the value should be between 0 and 1'
      stop
      endif
c --
c -- tii : the length of each simulation interval (minutes).
c -- ntt : the maximum number of simulation intervals.
c --
      read(43,*,iostat=error) itii
      tii=itii/60.0
c --
c -- kspstep : time interval for calculating the k shortest paths 
c --           (number of simulation intervals). 
c -- kupstep : time interval for updating the k shortest paths.
c --           (number of simulation intervals). 
c --
      read(43,*,iostat=error) kspstep,kupstep
c -- 
c -- Check for input errors
c --
      if(kupstep.ge.kspstep)then
      write(911,*) 'INPUT ERROR : scenario data file'
      write(911,*) 'kupstep is greater or equal to kspstep'
      write(911,*) 'kupstep should be < kspstep'
      stop
      endif
c -- 
c -- starttm : statistics will be collected for vehicles generated 
c --           after this time.
c -- starttm : statistics will be collected for vehicles generated 
c --           before this time.
      read(43,*,iostat=error) starttm,endtm
	if(starttm.ge.stagelength)then
	write(911,*) 'Simulation period is shorter than start time'
	write(911,*) 'For collecting statistics'
	write(911,*) 'Please correct'
	stop
	endif
c -- 
c -- Check for input errors
c --
      if(starttm.gt.stagelength)then
      write(911,*) 'INPUT ERROR : scenario data file'
      write(911,*) 'Warmup time is >= planning horizon'
      stop
      endif
      if(starttm.ge.endtm)then
      write(911,*) 'INPUT ERROR : scenario data file'
      write(911,*) 'Warmup time is >= end of stats collection time'
      stop
      endif
	MUC_Frac(:,:)=0
	Dem_Frac(:)=0
	Veh_Type(:)=0
	Dem_Mode(:)=0
	MUC_Mode(:)=0
	Numof_Veh_Type(:)=0
	Numof_Veh_Class(:)=0
	read(43,*) No_Veh_Types !number of vehicle types to be used in network
c	! need to check if zero vehicle types are used
	if(No_Veh_Types.lt.1)then
	write(911,*) 'Input Error: scenario.dat' 
	write(911,*)'The number of vehicles to be used in the network'
	write(911,*) 'must be at least 1'
	write(911,*) No_Veh_Types, '   vehicle types is specified'
	stop
	endif 
	do k=1,No_Veh_Types  !A-Level DO-LOOP
	Veh_Type_Tmp=0
	Dem_Frac_Temp=0
	MUC_Mode_Tmp=0
	Dem_Mode_Tmp=0
	MUC_Frac_Tmp(:)=0
      read(43,*,iostat=error) Veh_Type_Tmp,Dem_Mode_Tmp,Dem_Frac_Tmp,
     +MUC_Mode_Tmp, (MUC_Frac_Tmp(j),j=1,5) 
	if(error.ne.0)then
	write(911,*) 'error in reading scenario.dat'
	stop
	endif
c -- Veh_Type_Att_Tmp(1) returns the vehicle type
	   !Copy these values into respective arrays and check for input errors
	Veh_Type(Veh_Type_Tmp)=1
	Dem_Mode(Veh_Type_Tmp)=Dem_Mode_Tmp
         	!the demand mode must be either 0 or 1
	if(Dem_Mode(Veh_Type_Tmp).gt.0.and.
     +Dem_Mode(Veh_Type_Tmp).lt.1)then 
	write(911,*)'Error! scenario.dat'
      write(911,*)'The demand mode for vehicle type',
     +Veh_Type_Tmp, 'must be either 0 or 1'
	stop
	endif
	Dem_Frac(Veh_Type_Tmp)=Dem_Frac_Tmp
      	!the demand.dat fractions must be between 0 and 1.0
	if(Dem_Mode(Veh_Type_Tmp).eq.0)then !using demand.dat
	if(Dem_Frac(Veh_Type_Tmp).gt.1.0.and.
     +Dem_Frac(Veh_Type_Tmp).lt.0)then
	write(911,*)'Error! scenario.dat'
      write(911,*)'The demand.dat fraction for vehicle type',
     +Veh_Type_Tmp, ' must be between 0 and 1'
	stop
	endif
	endif	
	MUC_Mode(Veh_Type_Tmp)=MUC_Mode_Tmp
      	!the MUC mode must be either 0 or 1
	if(MUC_Mode(Veh_Type_Tmp).gt.0.and.
     +MUC_Mode(Veh_Type_Tmp).lt.1)then 
	write(911,*)'Error! scenario.dat'
      write(911,*)'The MUC mode for vehicle type',
     +Veh_Type_Tmp, ' must be either 0 or 1'
		stop
		  endif
		MUC_Frac_Sum=0 
		do j=1,5
	    MUC_Frac(Veh_Type_Tmp,j)=MUC_Frac_Tmp(j)
		!check if MUC fractions are between 0 and 1
	if(MUC_Mode(Veh_Type_Tmp).eq.1.or.Veh_Type_Tmp.eq.1)then 
	if(MUC_Frac(Veh_Type_Tmp,j).gt.1.0.or.
     +	MUC_Frac(Veh_Type_Tmp,j).lt.0)then
		write(911,*)'Error! scenario.dat'
                write(911,*)'The MUC fractions for vehicle type',
     + Veh_Type_Tmp, ' must be between 0 and 1'
		stop
	endif
c check if MUC fractions sum up to 1.0
	     MUC_Frac_Sum=MUC_Frac_Sum + MUC_Frac(Veh_Type_Tmp,j)
      	   endif
          enddo
c check if MUC fractions sum up to 1.0
        if(MUC_Mode(Veh_Type_Tmp).eq.1.or.Veh_Type_Tmp.eq.1)then 
      	if(MUC_Frac_Sum.lt.0.9999.or.MUC_Frac_Sum.gt.1.0001)then
		write(911,*)'Error! scenario.dat'
                write(911,*)'The MUC Fractions for vehicle type',
     +Veh_Type_Tmp, ' do not sum up to 1.0'
		stop
	     endif
	endif
	Enddo !A-Level DO-LOOP
       !Copy default MUC Proportions to all vehicle types having MUC mode = 0 
	do i=2,Max_No_Veh
	if(Veh_Type(i).ne.0.and.MUC_Mode(i).eq.0)Then !using default MUC distribution
		do j=1,5
		MUC_Frac(i,j)=MUC_Frac(1,j)
	        enddo
          endif
       enddo
       ! check if Dem_Frac sum up to 1.0
	  Dem_Frac_Sum=0
	do i=1,Max_No_Veh
	if(Veh_Type(i).ne.0.and.Dem_Mode(i).eq.0)Then !using default MUC distribution
		Dem_Frac_Sum=Dem_Frac_Sum+Dem_Frac(i)
	endif
	enddo
c	
	if(Dem_Frac_Sum.lt.0.9999.or.Dem_Frac_Sum.gt.1.0001)then
	   write(911,*)'Error! scenario.dat'
         write(911,*)'The specified fractions for demand.dat do not sum
     + up to 1.0'
         write(911,*)'Check the demand generation flag and corresponding 
     +   demand fractions'
	stop
	endif
c*********************************************************
c --
c -- no_class : number of vehicle classes in the network. Currently, there are 4 classes.
c --            1. vehicles with prespecified path.
c --            2. vehicles following System Optimal path
c --            3. vehicles following User Equilibrium path
c --            4. vehicles reaceiving en-route information (boundedly rational)
c --
c      read(43,*) no_class
c  --
c  -- iso_ok and iue_ok are indicators to know if we have SO or
c  -- UE vehicles in the network.  So, we should produce the
c  -- required output files for each procedure. 
c  --
      iso_ok=0
      iue_ok=0
	ienroute_ok=0
c      read(43,*,iostat=error) (classpro(i),i=1,nu_classes)
c	do i=1,No_Veh_Types
	do i=1,Max_No_Veh
c	if(realdm.eq.1.and.MUC_Frac(i,2).gt.0.001) iso_ok=1
c	if(realdm.eq.1.and.MUC_Frac(i,3).gt.0.001) iue_ok=1
c	if(realdm.eq.1.and.MUC_Frac(i,4).gt.0.001) ienroute_ok=1
	if(MUC_Frac(i,2).gt.0.001) iso_ok=1
	if(MUC_Frac(i,3).gt.0.001) iue_ok=1
	if(MUC_Frac(i,4).gt.0.001) ienroute_ok=1
      do j=2,nu_classes
      MUC_Frac(i,j)=MUC_Frac(i,j)+MUC_Frac(i,j-1) ! we are adding up MUC_Frac to make a random number draw
      enddo
	enddo
c --
      if(iteration.eq.0.and.stagest.eq.0) soda2=0
      if(iteration.gt.0.and.stagest.eq.0) soda2=1
      if(iteration.eq.0.and.stagest.gt.0) soda2=2
      if(iteration.gt.0.and.stagest.gt.0) soda2=3      
c   
c      endif
c --
c -- end of reading scenario file
	if(iso_ok.eq.1.or.iue_ok.eq.1)then
	noofnodes=noofnodes+noof_master_destinations+nzones
	else
	noofnodes=noofnodes+noof_master_destinations 
	endif 
c      print *, 'Alex240',nzones,nubus
	call allocate_dyna_network_node
      do i=1,noofnodes_org
C       if(EOF(41)) then
C	  ErString = "network.dat"
C	  call ErReadEOF(ErString)
C	 endif
      read(41,*,iostat=error) nodenum(i),izone(i) !%%%
	idnum(nodenum(i))=i
	if(error.ne.0)then
      write(911,*) 'error in reading nodes in network.dat',idnum(i)
	stop
	endif
      enddo
c      print *, 'Alex2401',nzones,nubus
	if(iso_ok.eq.1.or.iue_ok.eq.1)then
	do i=1,nzones
      origin(i)=noofnodes_org+i
	nodenum(origin(i))=800000+i 
c	! give origins external numbers starting from 800000
	idnum(nodenum(origin(i)))=noofnodes_org+i !G
      izone(origin(i))=i
	enddo
	endif
c	print *, 'Alex2402',nzones,nubus
c --  April 2001, Centroid Implementation
	do i=1,noof_master_destinations
c nzones takes care of the number of origins for all the zones
	if(iso_ok.eq.1.or.iue_ok.eq.1)then
	destination(i)=noofnodes_org+nzones+i
	else
      destination(i)=noofnodes_org+i
	endif
	nodenum(destination(i))=900000+i 
c give centroids external numbers starting from 9000
c nzones takes care of the number of origins for all the zones
	if(iso_ok.eq.1.or.iue_ok.eq.1)then
	idnum(nodenum(destination(i)))=noofnodes_org+nzones+i !G
	else
	idnum(nodenum(destination(i)))=noofnodes_org+i !G
	endif
      izone(destination(i))=i
	enddo
c --  End of Centroid Implementation
c	print *, 'Alex2403',nzones,nubus
	allocate(mmzonetmp(nzones))
c --  Going through the destination.dat to count how many artificial connecting links will be needed
      do i=1,nzones
C       if(EOF(53)) then
	!  ErString = "destination.dat"
	!which file needs to be reviewed
C        write(911,*) 'Error when reading destination.dat'
C	  write(911,*) 'More zones are specified in network.dat than in'
C       write(911,*) 'destination.dat'
C	  stop
	  !call ErReadEOF(ErString)
C	 endif
	read(53,*,iostat=error) kzonetmp,NoofConsPerZoneTmp
	   noofarcs=noofarcs+NoofConsPerZonetmp
	   mmzonetmp(i)=kzonetmp
	enddo    
      close(53)
c	print *, 'Alex2404',nzones,nubus
! Determine the number of additional connectors for origin zones
      if(iso_ok.eq.1.or.iue_ok.eq.1)then
c	print *, 'Alex2401'
      allocate(ConnectorToOriginFlag(noofnodes_org),stat=error)
	if(error.ne.0)then
	  write(911,*) 'allocate ConnectorToOriginFlag error -
     +	   insufficient memory'
	  stop
	endif
c	
      do i=1,nzones
	ConnectorToOriginFlag(:)=0
	SumLoadWeight=0.0
	read(52,*,iostat=error) izonetmp,NoofGenLinksPerZone(i),IDGen
c	print *,izonetmp,NoofGenLinksPerZone(i),IDGen,i
	if(error.ne.0)then
         write(911,*) 'Error when reading origin.dat 01'
	   stop
	endif
	 do j=1,NoofGenLinksPerZone(i)
         read(52,*,iostat=error) IUpNode,IDnNode,LWTmp !LWTmp is a temp var for LWTmp
 	   if (error.ne.0)then
           write(911,*) 'Error when reading origin.dat 02'
	   close(911)
	     stop
	   endif
	if(ConnectorToOriginFlag(idnum(IUpNode)).eq.0)then
	   ConnectorToOriginFlag(idnum(IUpNode))=1 !Used by node IUpNode
	   noofarcs=noofarcs+1
	endif
	enddo
	enddo
	rewind(52) !to reset pointer
	endif
	!specified in destination.dat
	do ia=1,nzones
	do MP=ia+1,nzones
	if(mmzonetmp(ia).eq.mmzonetmp(MP))then
	write(911,*) 'Error when reading destination.dat'
	write(911,*) 'Same zone number is specified twice'
	write(911,*) 'on lines',ia,' and', MP 
	write(911,*) 'Check destination.dat for duplication'
	write(911,*) 'of zone numbers'
	stop
	endif
	enddo
	enddo
	deallocate(mmzonetmp)
      if(NoofConsPerZoneTmp.lt.1)then
        write(911,*) 'Error in reading destination.dat'
	  write(911,*) 'Each zone needs to have at least one dest'
	  write(911,*) 'Please check zone',i
        stop
	endif
c	print *, 'Alex250',nzones,nubus
      call allocate_dyna_network_arc
c --  start reading GradeLengthPCE.dat
C      if(EOF(59)) then
C	 ErString = "GradeLengthPCE.dat"
C	 call ErReadEOF(ErString)
C	endif
      read(59,*,iostat=error) (TruckBPnt(i),i=1,TruckNum)
      do i=1,GradeNum
      read(59,*,iostat=error) GradeBPnt(i)
	 do j=1,LenNum
	 read(59,*,iostat=error) LengthBPnt(i,j),
     * (PCE(i,j,k),k=1,TruckNum)
       enddo
	enddo
c --
c -- Read link charateristics.
c --
c -- i3 : the link length in feet. s(i) : length of link i (in miles)
c -- i4 : a flag for vehicle generation from the current link.
c --              I4.eq.0 = not generation links
c --              I4.eq.1 = the demand generated on this link belongs to
c --                        the demadn generated from the zone which contains
c --                        the upstream node. 
c --              I4.eq.2 = the demand generated on this link belongs to
c --                        the demand generated from the zone which contains
c --                        the downstream node. 
c --
      Longest_link=0
	do 221 i=1,noofarcs_org
C       if(EOF(41)) then
C	  ErString = "network.dat"
C	  call ErReadEOF(ErString)
C	 endif
cbays from network.dat
c************* Start of Modification ***********************************
c      read(41,11,iostat=error)iu,id,MTbay,i3,nlanes(i),FlowModelNum(i)
c     *    ,Vfadjust(i),SpeedLimit(i),mfrtp,sattp,link_iden(i),LGrade(i)
      read(41,*,iostat=error)iu,id,MTbay,MTbayR,i3,nlanes(i),
     * FlowModelNum(i),Vfadjust(i),SpeedLimit(i),mfrtp,sattp,
     * link_iden(i),LGrade(i)
c************* End of Modification ***********************************
	if(error.ne.0)then
	write(911,*) 'error in reading link No. ',i, ':from',iu,'to',id
	stop
	endif
	if(SpeedLimit(i).lt.1)then
      write(911,*) 'Error in specifying speed limit'
	write(911,*) 'for link:',		i 
	write(911,*) 'Upstream Node:',	iu
	write(911,*) 'Downstream Node:',id
	SpeedLimit(i)= 45 ! need to be changed later on
c      stop
	endif
c might input a traffic flow model number that is greater than the total number
c of traffic models specified in TrafficModel.dat
	if((FlowModelNum(i)).gt.NoOfFlowModel)then 
      write(911,*) 'Error in specifying the traffic flow model number'
	write(911,*) 'for link:',		i 
	write(911,*) 'Upstream Node:',	nodenum(iunod(i))
	write(911,*) 'Downstream Node:',nodenum(idnod(i))
	write(911,*) 'The associated traffic model number in network.dat' 
	write(911,*) 'for the above link is:', FlowModelNum(i) 
	write(911,*) 'It cannot be greater than the total number of'
	write(911,*) 'traffic models specified in TrafficFlowModel.dat'
	write(911,*) 'which is:',		NoOfFlowModel
      stop
	endif
	OriginLinkIndex(i)=i
	if(error.ne.0)then
      write(911,*) 'error in reading network.dat at up/down node',iu,id
	stop
	endif
      if(MTbay.gt.0) bay(i)=MTbay
	if(MTbayR.gt.0) bayR(i)=MTbayR
	MaxFlowRateOrig(i)=float(mfrtp)/3600.0*nlanes(i)
	MaxFlowRate(i)=float(mfrtp)/3600.0*nlanes(i)
	SatFlowRate(i)=float(sattp)/3600.0*nlanes(i)
c both will time nlanes in next few blocks
c     if link is too short, adjust it according to VMAX and write out warning messages
      if(i3<(SpeedLimit(i)+Vfadjust(i))/60.0*528.0)then
      INQUIRE(UNIT=511,OPENED=Fexist)
	if(.not.Fexist)then
	open(file='Warning.dat',unit=511,status='unknown',iostat=error)
	if(error.ne.0) then
      write(911,*) 'Error when opening Warning.dat'
	stop
	endif
      endif
	write
     *(511,'("shortL",i7,"-> ",i7," LinkL",i6," VMAX",f4.1,"Min L",i6)')
     *   iu,id,i3,float(SpeedLimit(i)+Vfadjust(i)),
     *   ifix((SpeedLimit(i)+Vfadjust(i))/60.0*528.0)
	      i3 = (SpeedLimit(i)+Vfadjust(i))/60.0*528.0
	endif
c	
	if(MaxFlowRate(i).le.0.0001)then
        write(911,'("Check Saturation Flow for link #",i4)')i
	  stop
	endif
	if(nlanes(i).lt.1)then
        write(911,'("Check Number of Lanes for link #",i4)')i
	  stop
	endif
c	
	iunod(i)=idnum(iu) !G
	idnod(i)=idnum(id) !G
c	
11    format(2i7,2i5,i7,i3,i7,2i4,2i6,i3,i4)
c
c link_type 9 = hot on a freeway
c link_type 10 = hov on a freeway
c      if(link_iden(i).eq.6) then ! HOT links
      if(link_iden(i).eq.6.or.link_iden(i).eq.9)then ! HOT links
      link_hot=link_hot+1
      endif
c
c link_type 9 = hot on a freeway
c link_type 10 = hov on a freeway
c      if(link_iden(i).eq.8) then ! HOV links
      if(link_iden(i).eq.8.or.link_iden(i).eq.10)then ! HOV links
      link_hov=link_hov+1
      endif
c	
	if(i3*nlanes(i)/5280.0.gt.longest_link) 
     *longest_link=i3*nlanes(i)/5280.0
c --
         if(MTbay.lt.0.or.MTbay.gt.4)then
         write(911,*) 'INPUT ERROR : network.dat file'
         write(911,*) 'check the bay index for link number',i
         write(911,*) 'the value should be between 0 and 4'
	   write(911,*) 'the value entered is', MTbay
         stop
         endif
c --
c -- Check for input errors
c -- 
c if(link_iden(i).lt.1.or.link_iden(i).gt.8) then
	if(link_iden(i).lt.1.or.link_iden(i).gt.10)then
	write(911,*) ''
      write(911,*) 'INPUT ERROR in network.dat'
      write(911,*) 'check the link identification for link number',i
	write(911,*) 'upstream node:',nodenum(iunod(i))
	write(911,*) 'downstream node:',nodenum(idnod(i))
c     write(911,*) 'the value must be between 1 and 8'
	write(911,*) 'the value must be between 1 and 10'
	write(911,*) ''
      stop
      endif
      s(i)=float(i3)/5280.0
c
c --  determine GRDInd and LENInd
      Lenpnt=.False.
	Grdpnt=.False.           
        do ik=1,GradeNum
          if(LGrade(i).le.GradeBPnt(ik))then
            GRDInd(i)=ik
	      Grdpnt=.True.
	      exit
	  endif
	enddo
	if(.not.Grdpnt) GRDInd(i)=GradeNum
c	
	do ik=1,LenNum
      if(s(i).lt.LengthBPnt(GRDInd(i),ik))then
      LENInd(i)=ik
	Lenpnt=.True.
	exit
	endif
	enddo
      if(.not.Lenpnt) LENInd(i)=LenNum
c --
c -- Initialize the entry_service for the current link.
c --
      do ijk=1,nu_de
      entry_service(i,ijk)=entrymx*nlanes(i)*tii/60.0
      enddo
c	
221   continue ! end of reading link loop
c
c -- Check for input errors
c -- 
c        if(total_hov.gt.0.and.((link_hov+link_hot).lt.1)) then
        if(Veh_Type(3).gt.0.and.((link_hov+link_hot).lt.1))then
         write(911,*) 'INPUT ERROR : Found scenario.dat with HOV'
	   write(911,*) 'vehicles, but no HOV/HOT lanes are specified in'
	   write(911,*) 'network.dat'
         write(911,*) 'check the link identification for all links'
         write(911,*) 'the ID for HOT lanes is 6 or 9'
         write(911,*) 'the ID for HOV lanes is 8 or 10'
         stop
        endif
c	
c	print *, 'Alex260',nzones,nubus
c	
      call allocate_dyna_network_maxlinkveh
c	print *, 'Alex261',nzones

c
c --  Start to read destinations and 
c --  Start to create the connectors for destinations and centriods
	open(file='destination.dat',unit=53,status='old')      
      icount=0
      DO ia=1,nzones
	ConZoneTmp(:)=0
C       if(EOF(53)) then
C	  ErString = "destination.dat"
C	  call ErReadEOF(ErString)
C	 endif
	read(53,*,iostat=error) mzonetmp,NoofConsPerZone(ia),
     *           (ConZoneTmp(MP),MP=1,NoofConsPerZone(ia))
c	print *,mzonetmp,NoofConsPerZone(ia),
c     *           (ConZoneTmp(MP),MP=1,NoofConsPerZone(ia))
c Check for non-existing destination node in file destination.dat 
	do MP=1,NoofConsPerZone(ia)
	if(idnum(ConZoneTmp(MP)).eq.0)then
	write(911,*) 'Error when reading destination.dat'
	write(911,*) 'The destination node:',ConZoneTmp(MP)
	write(911,*) 'for zone:',ia,' does not exist'
	write(911,*) 'Check network.dat for the list of existing nodes'
	stop
	endif
	enddo

c	print *, 'Alex261a',mzonetmp,NoofConsPerZone(ia),
c     *           (ConZoneTmp(MP),MP=1,NoofConsPerZone(ia))
		
	if(error.ne.0)then
      write(911,*) 'Error when reading destination.dat'
	stop
	endif

c	print *, 'Alex261b',nzones

	if(NoofConsPerZone(ia).lt.1)then
      write(911,'("Error in destination.dat")') 
	write(911,'("Found zone",i4," contains no destination")')ia
	stop
	endif

      do MM=1,NoofConsPerZone(ia)
      if(ConZoneTmp(MM).lt.1)then
      write(911,*) 'Error in destination.dat, zone',ia
	write(911,*) 'check number of zones and zone numbers'
	stop
	endif
	enddo
c	
      if(NoofConsPerZone(ia).gt.0)then	  
	do j=1,NoofConsPerZone(ia)
      ConNoInZone(ia,j)=ConZoneTmp(j)
      icount=icount+1
	iline=noofarcs_org+icount
      iunod(iline)=idnum(ConNoInZone(ia,j))
      idnod(iline)=destination(MasterDest(mzonetmp))
      SpeedLimit(iline)=100
	FlowModelNum(iline)=NoOfFlowModel+1 ! the third type is for connector only
      Vfadjust(iline)=0
c         bay(iline)=.False.
      bay(iline)=0
      nlanes(iline)=10
      link_iden(iline)=99   
      MaxFlowRate(iline)=100.0
      SatFlowRate(iline)=100.0
      s(iline)=0.05
      entry_service(iline,1:nu_de)=1
      LoadWeight(iline)=0.0
      LGrade(iline)=0.0
      GRDInd(iline)=1
	LENInd(iline)=1
	OriginLinkIndex(iline)=0
	enddo
	endif

	ENDDO
	
c	print *, 'Alex261c',nzones

c --  updates the iConzone: which super zone that destination i connects to
      do i=1,noofnodes
        do j=1,nzones
	    do k=1,NoofConsPerZone(j)
            if(i.eq.idnum(ConNoInZone(j,k)))then
              iConZone(i,1)=iConZone(i,1)+1
	        if(iConZone(i,1).gt.2)then
	        !write(911,*) "Only max 2 centroids that a connector"
	        !write(911,*) "Can connect to"
                !write(911,*) "Review zone",j," node", i 
		!write(911,*) "in your destination.dat"
	        write(911,*) "A max of 2 zones may share a destination"
                write(911,*) "Destination node",ConNoInZone(j,k) 
        	write(911,*) "Has been used more than twice"
	        write(911,*) "Check zone",j,"    in destination.dat"
	          stop
	        endif
	        iConZone(i,iConZone(i,1)+1)=j
	      endif
	    enddo
	  enddo
	enddo
c --
c -- end of reading network file (fort.41)
c --
c	IF(realdm.eq.1)THEN
c
c -- read demand data (fort.42).
c -- if soda2 = 1 or 3, then vehicle and path files are provided and
c -- there is no need to read the demand file.
c --
c -- nints : number of demand intervals
c -- multi : multiplication factor for the demand (i.e. each value in the
c --         provided OD matrix will be multiplied by this factor to specify
c --         the number of vehicle generated from each zone to each destination.
c --
C       if(EOF(42)) then
C	  ErString = "demand.dat"
C	  call ErReadEOF(ErString)
C	 endif
c	
c	print *, 'Alex270',nzones,nubus

      read(42,*,iostat=error) (begint(i),i=1,nints+1)
      if(nintsT.gt.0) read(54,*) (begintT(i),i=1,nints+1)
      if(nintsH.gt.0) read(61,*) (begintH(i),i=1,nints+1)
c -- 
c -- Check for input errors
c --
        do k=2,nints+1
         if(begint(k-1).ge.begint(k))then
         write(911,*) 'INPUT ERROR : demand data file'
         write(911,*) 'check the start of the', k-1,'th demand interval'
         write(911,*) 'and the', k, 'th interval.'
         stop
         endif
        enddo
c --
c -- Initialize the counter for the demand intervals (int) 
c --
c -- read the zonal time-dependent demand data matrix
c -- 	
      allocate(demtmp(nzones))
c	
      demandsum=0
      do 223 int=1,nints
	if(begint(int).ge.stagelength) exit 
	! only count vehicle those demand matrices within stagelength
	read(42,*,iostat=error)
      DO 223 iz=1,nzones
	demtmp(:)=0
      read(42,*,iostat=error) (demtmp(izz),izz=1,nzones)
c	
	if(error.ne.0)then
           write(911,*) 'Error when reading demand.dat'
	   write(911,*) 'Fewer zones are specified in network.dat than'
	   write(911,*) 'Provided for in demand.dat'
	   stop
	endif
	  do ioz=1,nzones
	  demandsum=demandsum+demtmp(ioz)*multi
	  enddo
223   continue
c	print *, 'Alex271',nzones,nubus

c --
      if(realdm.eq.1)then
	MaxVehicles=nint(demandsum*1.02)
c	print *, 'MaxVehicles=',MaxVehicles
	endif	  
c	
      rewind(42)
	read(42,*)
	read(42,*)
! --  For truck demand
	demandsumT=0.0
	if(nintsT.gt.0)then
c	
      do 2233 int=1,nintsT
C       if(EOF(54)) then
C	  ErString = "demand_truck.dat"
C	  call ErReadEOF(ErString)
C	 endif
	read(54,*,iostat=error)
c	print *, 'Alex272',nzones,nubus
      DO 2233 iz=1,nzones
      read(54,2244,iostat=error) (demtmp(izz),izz=1,nzones)
	if(error.ne.0)then
         write(911,*) 'Error in input when reading demand_truck.dat'
	   stop
	endif
	  do ioz=1,nzones
	  demandsumT=demandsumT+demtmp(ioz)*multiT
	  enddo
2233  continue
2244  format(6f10.4)
c
c	print *, 'Alex273',nzones,nubus	
      rewind(54)
	read(54,*,iostat=error)
	read(54,*,iostat=error)
c	print *, 'Alex274',nzones,demandsumT	
! -- if demand_truck.dat exist update classpro2
	if(demandsumT.gt.0)then !if demand_truck.dat is used
	! then update the original fraction of vehicle types
	! keeping in mind that vehicle type fractions in scenario.dat apply only to 
	! demand.dat 
c	
	do i=1,6
		if(i.ne.2.and.i.ne.5)then !excluding trcuks w/o info and w/ info 
		classpro2(i)=OrigVehFrac(i)*demandsum/(demandsum+demandsumT)
		elseif(i.eq.2)then ! if truck type w/o info
	classpro2(i)=(OrigVehFrac(i)*demandsum+(1-fracinf)*demandsumT) 
		classpro2(i)=classpro2(i)/(demandsum+demandsumT)
		elseif(i.eq.5)then ! if truck type w/ info
	classpro2(i)=(OrigVehFrac(i)*demandsum+fracinf*demandsumT) 
		classpro2(i)=classpro2(i)/(demandsum+demandsumT)
		endif
	enddo
c	print *, 'Alex275',nzones
	total_hov=classpro2(3)+classpro2(6)

	do i=1,3 !update cummulative probability of vehicle types w/o info
		if (i.eq.1)then  
	classpro2(i)=classpro2(i)/(classpro2(i)+classpro2(i+1)+ !initialzing 
     *                                 classpro2(i+2))		
		else
		classpro2(i)=(classpro2(i)/(1-fracinf))+classpro2(i-1)
		endif
	 enddo 
c	print *, 'Alex276',nzones	
	do i=4,6 !update cummulative probability of vehicle types w/o info
		if (i.eq.4)then
	if((classpro2(i)+classpro2(i+1)+
     *   classpro2(i+2)).gt.0.00001)then	        
	classpro2(i)=classpro2(i)/(classpro2(i)+classpro2(i+1)+ !initialzing and normalizing
     *                                 classpro2(i+2))
	endif		
		else
	if(fracinf.gt.0.00001)then 
		classpro2(i)=(classpro2(i)/(fracinf))+classpro2(i-1)
	endif
		endif
	enddo 
	endif	
c********** End of addition *******************
      endif
c*************************demand_HOV***************
c added by MTI to count the number of HOV vehicles 
c --  For HOV demand
c	
c	  print *, 'Alex280',nzones,nubus

	  demandsumH=0.0
	  if(nintsH.gt.0)then
      do int=1,nintsH
C       if(EOF(61)) then
C	  ErString = "demand_HOV.dat"
C	  call ErReadEOF(ErString)
C	  endif
	  read(61,*,iostat=error)
c	
	  DO iz=1,nzones
      read(61,2244,iostat=error) (demtmp(izz),izz=1,nzones)
	  if(error.ne.0)then
         write(911,*) 'Error in input when reading demand_HOV.dat'
	   stop
	  endif
	  do ioz=1,nzones
	  demandsumH=demandsumH+demtmp(ioz)*multiH
	  enddo
	  enddo
	  enddo
c	
      rewind(61)
	  read(61,*,iostat=error)
	  read(61,*,iostat=error)
	  endif
c	  print *, 'Alex290',nzones,nubus
c******************************************************************
      	if(realdm.eq.1)then
c need to add HOV vehicles from demand_HOV
c	   MaxVehicles = MaxVehicles + nint((demandsumT)*1.05) 
	   MaxVehicles=MaxVehicles*1.2+nint((demandsumT)*1.2) 
     +   +nint((demandsumH)*1.2)
c	  print *,'MaxVehicles2=',MaxVehicles
	  endif
c	  print *, 'Alex270',nzones,nubus
	  call allocate_dyna_vehicle
c	  print *, 'Alex270a',nzones,nubus
c --
c --  end of reading the demand data (fort.42)
c --
c	  ENDIF
c --
c --  Read the signal control data file.  This file reads only the
c -- first line of the file, then it calls read_signals at the end.  
c --
c -- isig : number of signal setting plans.
c -- startsig : start time for each signal plan.
c -- isigcount : a counter to keep track of the signal plan to 
c -- be activated when the clock time is equal to its start.
c --
C       if(EOF(44)) then
C	  ErString = "control.dat"
C	  call ErReadEOF(ErString)
C	  endif
	  read(44,*,iostat=error) (strtsig(i),i=1,isig)
        strtsig(isig+1)=2*stagelength
	  isigcount=1
c --
c -- start reading the ramp metering data.
c --
c -- array definition :  detector(i,7)
c -- (i,1): detector number
c --    2 : from node
c --    3 : to node
c --    from and to nodes define the downstream link for the metered ramp.
c --    4 : position of the first detector on the downstream link (in feet). 
c --    5 : position of the second detector on the downstream link (in feet).
c --    both distances in 4 and 5 are measured from the downstream node. 
c --    6 : upstream  node of the metered ramp
c --    7 : downstream  node of the metered ramp
c --
c --    ramp_par(i,3)
c --       1 : cons1, used in RATE=RATEP+cons1(cons2-OCC)
c --       2 : cons2
c --      According to simulation experiments, the default values of 
c --      cons1 and cons2 are 0.32 and 0.2 respectively and these values 
c --      may be calibrated using actual data.
c --       3 : ramp rate (sturation flow rate on the ramp veh/sec/lane)
c --
c -- nrate : the time interval for checking the ramp metering (in minutes)
c --
c      print *, 'Alex2701',nzones,nubus
    	if(dec_num.gt.0)then
      do 455 i=1,dec_num
C       if(EOF(45)) then
C	  ErString = "ramp.dat"
C	  call ErReadEOF(ErString)
C	  endif
      read(45,*,iostat=error)(detector(i,j),j=1,7),
     *(ramp_par(i,j),j=1,3)
	  if(error.ne.0) then
         write(911,*) 'Error when reading ramp.dat'
	   stop
	  endif
! **********************************************
c	print *, 'Alex2702',nzones,nubus
	  if(idnum(detector(i,2)).gt.0)then
		detector(i,2)=idnum(detector(i,2))!G  //copy back internal node number
	  else
	  write(911,*) 'INPUT ERROR: RAMP.DAT' 
	  write(911,*) 'node', detector(i,2),   
     + '   does not exist in network.dat'
	  stop
	  endif
	  if(idnum(detector(i,3)).gt.0)then
		detector(i,3)=idnum(detector(i,3))!G//copy back internal node number
	  else
	  write(911,*) 'INPUT ERROR: RAMP.DAT '
	  write(911,*) 'node', detector(i,3),   
     + '   does not exist in network.dat'
	  stop
	  endif
c	print *, 'Alex2703',nzones,nubus
	  if(idnum(detector(i,6)).gt.0)then
		detector(i,6)=idnum(detector(i,6))!G//copy back internal node number
	  else
	  write(911,*) 'INPUT ERROR: RAMP.DAT' 
	  write(911,*) 'node', detector(i,6),   
     + '   does not exist in network.dat'
	  stop
	  endif
	  if(idnum(detector(i,7)).gt.0)then
		detector(i,7)=idnum(detector(i,7))!G//copy back internal node number
	  else
	  write(911,*) 'INPUT ERROR: RAMP.DAT' 
	  write(911,*) 'node', detector(i,7),   
     + '   does not exist in network.dat'
	  stop
	  endif
!********************************************************
c	  print *, 'Alex2704',nzones,nubus
      detector_length(i)=detector(i,4)-detector(i,5)
c --
c -- Check for input errors
c --
       if(detector_length(i).le.0)then
         write(911,*) 'INPUT ERROR : Ramp metering data'
         write(911,*) 'the detector length for ramp number ',i
         write(911,*) 'is <= zero.  Please check the input file'
         stop
       endif
c --
      read(45,*,iostat=error) ramp_start(i),ramp_end(i)
455   continue
      endif
c --
c --  link_dectector(i) : defines the detector number which exist on link i.
c --   det_link(j) : defines the link number for detector j.
c --   detector_ramp(j) : the ramp controlled by detector j.
c --
c --   set link_detector and det_link
c -- 
c      print *, 'Alex2705',nzones,nubus
      if(dec_num.gt.0)then
      do i=1,dec_num
         do j=1,noofarcs
            if(detector(i,2).eq.iunod(j).and.
     +      detector(i,3).eq.idnod(j))then
               link_detector(j)=i
            endif
            if(detector(i,2).eq.iunod(j).and.
     +      detector(i,3).eq.idnod(j))then
               det_link(i)=j
            endif
            if(detector(i,6).eq.iunod(j).and.
     +      detector(i,7).eq.idnod(j))then
               detector_ramp(i)=j
            endif
          enddo
c --
c -- Check for input errors
c --
         if(det_link(i).eq.0)then 
      write(911,*) 'INPUT ERROR!: ramp.dat input file'
      write(911,*) 'Check the detector link for metered ramp number',i

	  write(911,*) 'Link',nodenum(detector(i,2)),'   -->',  
     +nodenum(detector(i,3)),'    does not exist in network.dat'	 
	  stop
      endif
c --
c*********************************************************************
c	  print *, 'Alex2706',nzones,nubus
	  if(detector_ramp(i).eq.det_link(i))then
	  write(911,*) 'INPUT ERROR!: RAMP.DAT' 
        write(911,*)'The freeway detector link and ramp 
     +  link are the same'
	  stop
	  endif
       if((detector(i,4).gt.5280*s(det_link(i))).or.
     +  (detector(i,5).gt.5280*s(det_link(i))))then
         write(911,*) 'INPUT ERROR: Ramp metering data'
         write(911,*) 'Location of detectors are out of range'
	write(911,*)'The value entered is larger than the length of the'
      write(911,*)'freeway link',nodenum(detector(i,2)),'   -->',
     + nodenum(detector(i,3))
	  write(911,*)'Which is',s(det_link(i))*5280,   'feet'
         stop
       endif
      if(detector_ramp(i).eq.0)then 
      write(911,*) 'INPUT ERROR!: ramp.dat input file'
      write(911,*) 'Check the ramp link for metered ramp number',i
	  write(911,*) 'Ramp',detector(i,6),'   -->',  
     +detector(i,7),'    does not exist in network.dat'	 
	  stop
         endif
c**************************************************************************
      enddo
	  endif
c --
c -- end read ramp metering data
c --
c	 print *, 'Alex2707',nzones,nubus
c re-duplicated from reading generation.dat
c********************************************************************
c********************************************************************
c --  Starting Reading origin.dat
c --  NoofGenLinksPerZone is read from origin.dat:izlins
c --  LinkNoInZone() keeps track of the link number:izone
c --  total link length for zones are stored in TotalLinkLenPerZone():totlmz
c This part just takes care of adding connectors for origin zones   
c	
      do i=1,nzones
c	 print *, 'Alex27070'
	if(iso_ok.eq.1.or.iue_ok.eq.1)then
	 ConnectorToOriginFlag(:)=0
	endif
c	print *, 'Alex27071'
	 SumLoadWeight=0.0
c	print *, 'Alex27072'
	 read(52,*,iostat=error) izonetmp,NoofGenLinksPerZone(i),IDGen
	  if(error.ne.0) then
      write(911,*) 'Error when reading origin.dat 03'
	 stop
      endif
c	print *, 'Alex27073'
      do j=1,NoofGenLinksPerZone(i)
          read(52,*,iostat=error) IUpNode,IDnNode,LWTmp !LWTmp is a temp var for LWTmp
	  if(iso_ok.eq.1.or.iue_ok.eq.1)then
	    if(ConnectorToOriginFlag(idnum(IUpNode)).eq.0.)then
         	icount=icount+1 ! icount has been used in reading destination.dat
	 	iline=noofarcs_org+icount
         	iunod(iline)= origin(izonetmp)
         	idnod(iline)= idnum(IUpNode)
	 	ConnectorToOriginFlag(idnum(IUpNode))=1 !Used by node IUpNode
         	SpeedLimit(iline)=100
	 	FlowModelNum(iline)=NoOfFlowModel+1 ! the third type is for connector only
         	Vfadjust(iline)=0
c         bay(iline)=.False.
         	bay(iline)=0
         	nlanes(iline)=3
         	link_iden(iline)=100   
         	MaxFlowRate(iline)=100.0
         	SatFlowRate(iline)=100.0
         	s(iline)=1.00
         entry_service(iline,1:nu_de)=entrymx*nlanes(i)*tii/60.0
         	LoadWeight(iline)=0.0
         	LGrade(iline)=0.0
         	GRDInd(iline)=1
	 	LENInd(iline)=1
	 	OriginLinkIndex(iline)=0
	    endif
           endif
	 enddo
	enddo
	rewind(52) !to reset pointer
c --  sort all the links to be forward *, only need to sort up and downstream nodes 
c     since all other arrays are identical for the two 
c --  sort upstream nodes first, then downstream nodes
c	print *, 'Alex280',nzones,nubus
      do i=1,noofarcs-1
	  do j=i+1,noofarcs
	    if(iunod(j).lt.iunod(i))then
	      call SwapIntArray2B(iunod(i),iunod(j))
            call SwapIntArray2B(idnod(i),idnod(j))
c	      call SwapLogArray(bay(i),bay(j))
	      call SwapIntArray1B(bay(i),bay(j))
		     call SwapIntArray1B(bayR(i),bayR(j))
            call SwapIntArray1B(nlanes(i),nlanes(j))
            call SwapIntArray2B(link_iden(i),link_iden(j))
            call SwapRealArray(MaxFlowRate(i),MaxFlowRate(j))
            call SwapRealArray(MaxFlowRateOrig(i),MaxFlowRateOrig(j))
            call SwapRealArray(SatFlowRate(i),SatFlowRate(j))
            call SwapRealArray(s(i),s(j))
	      call SwapIntArray1B(FlowModelNum(i),FlowModelNum(j))
            call SwapIntArray2B(Vfadjust(i),Vfadjust(j))
            call SwapIntArray2B(SpeedLimit(i),SpeedLimit(j))
            call SwapIntArray1B(LGrade(i),LGrade(j))
            call SwapIntArray2B(GRDInd(i),GRDInd(j))
            call SwapIntArray2B(LENInd(i),LENInd(j))
            call SwapIntArray2B(OriginLinkIndex(i),OriginLinkIndex(j))
	    endif
	  enddo
	enddo 
c  -- Sort downstream node given the same upstream nodes
      do i=1,noofarcs-1
        do j=i+1,noofarcs
            if (iunod(j).eq.iunod(i))then
		    if (idnod(j).lt.idnod(i))then
 	         call SwapIntArray2B(iunod(i),iunod(j))
               call SwapIntArray2B(idnod(i),idnod(j))
!	         call SwapLogArray(bay(i),bay(j))
	call SwapIntArray1B(bay(i),bay(j))
	call SwapIntArray1B(bayR(i),bayR(j))
               call SwapIntArray1B(nlanes(i),nlanes(j))
               call SwapIntArray2B(link_iden(i),link_iden(j))
               call SwapRealArray(MaxFlowRate(i),MaxFlowRate(j))
               call SwapRealArray(MaxFlowRateOrig(i),MaxFlowRateOrig(j))
               call SwapRealArray(SatFlowRate(i),SatFlowRate(j))
               call SwapRealArray(s(i),s(j))
	call SwapIntArray1B(FlowModelNum(i),FlowModelNum(j))
               call SwapIntArray2B(Vfadjust(i),Vfadjust(j))
               call SwapIntArray2B(SpeedLimit(i),SpeedLimit(j))
               call SwapIntArray1B(LGrade(i),LGrade(j))
               call SwapIntArray2B(GRDInd(i),GRDInd(j))
               call SwapIntArray2B(LENInd(i),LENInd(j))
              call SwapIntArray2B(OriginLinkIndex(i),OriginLinkIndex(j))
              endif
	      else
	        exit
            endif
	  enddo
	enddo
c	print *, 'Alex290',nzones,nubus
! Prepare network after adding connectors
      call prepare_network()
! Assign link numbers to array LinkNoInZone
c	print *, 'Alex2901',nzones,nubus
      do i=1,nzones
	SumLoadWeight=0.0
	read(52,*,iostat=error) izonetmp,NoofGenLinksPerZone(i),IDGen
	if(error.ne.0) then
         write(911,*) 'Error when reading origin.dat 04'
	   stop
	endif
c	
	 do j=1,NoofGenLinksPerZone(i)
         read(52,*,iostat=error) IUpNode,IDnNode,LWTmp !LWTmp is a temp var for LWTmp

 	   if(error.ne.0)then
           write(911,*) 'Error when reading origin.dat 05'
	     stop
	   endif
    	   if(idnum(IUpNode).gt.0.and.idnum(IDnNode).gt.0)then
	   LinkNo=GetFLinkFromNode(idnum(IUpNode),idnum(IDnNode))
!****************************
  	   	   if(LinkNo.lt.1)then
	      write(911,*) 'Error in origin.dat 06'
          write(911,*) 'Link', IUpNode,'  ->', IDnNode,'   does not exit
     + for zone', i	 
            write(911,*) 'If the link does in fact exist in network.dat, 
     + then check if the number of'
       write(911,*)'generation links is mis-specified for 
     + any of the zones'   
		  stop 
	   endif
!**********************************************************
      else
	    write(911,*) 'Error in origin.dat 07'
          write(911,*) 'Link', IUpNode,'  ->', IDnNode,'   does not exit
     + for zone', i	 
            write(911,*) 'If the link does in fact exist in network.dat, 
     + then check if the number of'
      write(911,*)'generation links is mis-specified for 
     +any of the zones'   
		  stop 
      endif
	!if(link_iden(LinkNo).eq.6) then
	!**************************
	  if((link_iden(LinkNo).eq.6).or.(link_iden(LinkNo).eq.9).or.
     +	(link_iden(LinkNo).eq.8).or.(link_iden(LinkNo).eq.10))then
      INQUIRE(UNIT=511,OPENED=Fexist)
	if(.not.Fexist)then
	open(file='Warning.dat',unit=511,status='unknown',iostat=error)
	if(error.ne.0) then
      write(911,*) 'Error when opening Warning.dat'
	stop
	endif
	endif
		 write(511,'("Error in origin.dat 08")')
	     write(511,'("link ",i5," -->",i5," is an HOT/HOV link")') 
     *                   IUpNode,IDnNode
	  write(511,'("It cannot be a generation link in zone",i3)') i 
	    endif			
!*****************************************************************

		if(link_iden(LinkNo).eq.1)then
      INQUIRE(UNIT=511,OPENED=Fexist)
	if(.not.Fexist)then
	open(file='Warning.dat',unit=511,status='unknown',iostat=error)
	if(error.ne.0) then
      write(911,*) 'Error when opening Warning.dat'
	stop
	endif
	endif
           write(511,'("Error in origin.dat 09")')
	     write(511,'("link ",i5," -->",i5," is highway/freeway")') 
     *                   IUpNode,IDnNode
	  write(511,'("It cannot be a generation link in zone",i3)') i 
!	     stop
	   endif
!	   if(LinkNo.lt.1) then
!	      write(911,*) 'Error in origin.dat'
!            write(911,*) 'Link doesnt exit'
!            write(911,*) 'zone, ud, nd', i, IUpNode, IDnNode
!	      stop 
!	   endif
	  LinkNoInZone(i,j)=LinkNo
	  LGenerationFlag(LinkNo)=i
	  enddo
	  enddo
	  rewind(52) !to reset pointer
c --
c -- start read movement data
c --
      do i=1,noofarcs
      move(i,nu_mv+1)=llink(i,nu_mv+1)
      movein(i,nu_mv+1)=inlink(i,nu_mv+1)
      enddo
c --
c --
cccccc we still read movement.dat based on the 
cccccc  the old number of links
      do 100 i=1,noofarcs_org
      ifrom=0
      ito=0
      mlink=0
      mleft=0
      mst=0
      mright=0
      mother1=0
      mother2=0
      mother3=0
      mother4=0
      muturn=0
	iuturn_flag=0
10    format(8i7)
c
c10    format(10i7)
c
C       if(EOF(47)) then
C	  ErString = "movement.dat"
C	  call ErReadEOF(ErString)
C	  endif
      read(47,*,iostat=error) 
     +ifrom,ito,ileft,ist,iright,iother1,iother2,iuturn_flag
	  if(error.ne.0)then
      write(911,*) 'Error when reading movement.dat'
	  stop
	  endif
c --   check if ito is connecting to centriods.  
!      Max 2 conections as represented in i1 and i2
      mflag=0
	  iother3=0
	  iother4=0
      do mp=1,nzones
         do mn=1,NoofConsPerZone(mp)
            if(ito.eq.ConNoInZone(mp,mn))then
	         mflag=mflag+1
	         if(mflag.eq.1)then
	           iother3=nodenum(destination(MasterDest(mp)))
	         elseif(mflag.eq.2)then
	           iother4=nodenum(destination(MasterDest(mp)))
               elseif(mflag.gt.2)then
                 write(911,*) "DYNASMART-P only allows max 2 centriods"
                 write(911,*) "That each connector could connect to"
	           write(911,*) "Please check your destination.dat"
                 stop
	         endif
	      endif
         enddo
	  enddo
! --  determine the movement type
      if(ifrom.ne.0.and.ito.ne.0)
     *   mlink=GetFLinkFromNode(idnum(ifrom),idnum(ito))
      if(ito.ne.0.and.ileft.ne.0)
     *   mleft=GetFLinkFromNode(idnum(ito),idnum(ileft))
      if(ito.ne.0.and.ist.ne.0)
     *   mst=GetFLinkFromNode(idnum(ito),idnum(ist))
      if(ito.ne.0.and.iright.ne.0)
     *   mright=GetFLinkFromNode(idnum(ito),idnum(iright))
      if(ito.ne.0.and.iother1.ne.0)       
     *   mother1=GetFLinkFromNode(idnum(ito),idnum(iother1))
      if(ito.ne.0.and.iother2.ne.0)
     *   mother2=GetFLinkFromNode(idnum(ito),idnum(iother2))
      if(ito.ne.0.and.iother3.ne.0)
     *   mother3=GetFLinkFromNode(idnum(ito),idnum(iother3))
      if(ito.ne.0.and.iother4.ne.0)
     *   mother4=GetFLinkFromNode(idnum(ito),idnum(iother4))
      jfind=0
c --  jfind = 1 means an U turn physically exists from ifrom->ito
      KK=GetBLinkFromNode(idnum(ito),idnum(ifrom))
 	if(KK.gt.0)then
 !       if(idnum(ito).eq.(KK)) then
 !		if(idnod(mlink).eq.idnod(kk)) then
         jfind=1
!	  endif
	UturnFlag(mlink)=iuturn_flag  !copy from movement.dat 
	if(jfind.gt.0)then
!************************
!      if(link_iden(GetFLinkFromNode(idnum(ifrom),idnum(ito))).ne.1.or.
!     *   link_iden(GetFLinkFromNode(idnum(ifrom),idnum(ito))).ne.2) 
      if(link_iden(GetFLinkFromNode(idnum(ifrom),idnum(ito))).ne.1.or.
     *   link_iden(GetFLinkFromNode(idnum(ifrom),idnum(ito))).ne.2.or.
     *   link_iden(GetFLinkFromNode(idnum(ifrom),idnum(ito))).ne.9.or.
     *   link_iden(GetFLinkFromNode(idnum(ifrom),idnum(ito))).ne.10) 
!***********************************************
     *   muturn=GetFLinkFromNode(idnum(ito),idnum(ifrom)) !Forward * link # of ifrom->ito is not freeway
	!if not a freeway, then muturn is positive
	endif
!	endif
!********************
!	if((muturn.gt.0.or.jfind.gt.0).and.iuturn_flag.eq.1) then
	if((muturn.eq.0).and.(jfind.gt.0).and.(iuturn_flag.eq.1))then
! If a freeway link with an allowed uturn and if a physical u-turn exists
! then prohibit that uturn 
	UturnFlag(mlink)=0
	write(511,*)
	write(511,*) 'A u-turn has been specified on a freeway'
	write(511,*) 'link', ifrom,  '   -->',ito
	write(511,*) 'The u-turn has been internally prohibited'
	write(511,*)
	endif
	kkk=mlink !to temporary store mlink
	 !if user prohibits u-turns on a generation link, internally 
	 !allow u-turns on that links
	if(jfind.gt.0.and.iuturn_flag.eq.0)then 
	!physical u-turn exists, but prohibited by user
		do iii=1,nzones
			do jjj=1,NoofGenLinksPerZone(iii)
			if (kkk.eq.LinkNoInZone(iii,jjj))then
	UturnFlag(kkk)=1
	write(511,*)
	write(511,*) 'The user prohibited u-turn on a generation link'
	write(511,*) 'link', ifrom,'   -->',ito
	write(511,*) 'The u-turn has been internally allowed'
	write(511,*)
			endif
			enddo
		enddo
	endif

!*********************
	else
! No physical U turn exists
!	if(jfind.eq.0.or.iuturn_flag.eq.1) then
	if((jfind.eq.0).and.(iuturn_flag.eq.1))then
	UturnFlag(mlink)=0
	write(511,*)
	write(511,*) 'A u-turn has been specified on a link where'
	write(511,*) 'a u-turn does not physically exist'
      write(511,*) 'Link',ifrom,  '   -->',ito
	write(511,*) 'The u-turn has been internally prohibited'
	write(511,*)
	endif
	endif
c --
c -- Check for input errors
c --
         if(mlink.eq.0)then 
          write(911,*) 'INPUT ERROR : movement data file'
          write(911,*) 'check the upstream and down stream' 
          write(911,*) 'nodes for line number',i
	    write(911,*) iunod(i),idnod(i)
          stop
         endif
c --
c -- Check for input errors
c --
         if(mleft.eq.0.and.ileft.ne.0)then 
          write(911,*) 'INPUT ERROR : movement data file'
          write(911,*) 'check the left turning movement' 
          write(911,*) 'for line number',i
          write(911,*) mleft,ileft
		stop
         endif
c --
c -- Check for input errors
c --
         if(mst.eq.0.and.ist.ne.0)then 
          write(911,*) 'INPUT ERROR : movement data file'
          write(911,*) 'check the through movement' 
          write(911,*) 'for line number',i
          write(911,*) mst,ist
		stop
         endif
c --
c -- Check for input errors
c --
         if(mright.eq.0.and.iright.ne.0)then 
          write(911,*) 'INPUT ERROR : movement data file'
          write(911,*) 'check the right turning movement' 
          write(911,*) 'for line number',i
          write(911,*) mright,iright
		stop
         endif
c --
c -- Check for input errors
c --
         if(mother1.eq.0.and.iother1.ne.0)then 
          write(911,*) 'INPUT ERROR : movement data file'
          write(911,*) 'check the other movement' 
          write(911,*) 'for line number',i
	    write(911,*) ifrom,ito,mother1,iother1 
          stop
         endif
c --
c -- Check for input errors
c --
         if(mother2.eq.0.and.iother2.ne.0)then 
          write(911,*) 'INPUT ERROR : movement data file'
          write(911,*) 'check the other_i1 movement' 
          write(911,*) 'for line number',i
	    write(911,*) ifrom,ito,mother2,iother2
          stop
         endif
c --
c -- define the movement numebr
c -- left turn =1
c -- straight movement =2
c -- right movement =3
c -- other movement1 =4
c -- other movement2 =5
c -- U-turn =6
c -- other movement3 =7
c -- other movement3 =8
c --
              j=mlink
              do k=1,llink(j,nu_mv+1)
		        if(llink(j,k).eq.mleft)then
			     move(j,k)=1
! To take into account prevented movements defined in movement.dat
!           MVPF = MoveNoForLink(j,llink(j,k))
!           GeoPreventFor(llink(j,k),MVPF) = 0 ! allowed
	GeoPreventFor(j,k)=0 ! allowed
            MVPB=MoveNoBackLink(j,llink(j,k))
            GeoPreventBack(ForToBackLink(llink(j,k)),MVPB) = 0 ! allowed
                elseif(llink(j,k).eq.mst)then
			     move(j,k)=2
! To take into account prevented movements defined in movement.dat
!           MVPF = MoveNoForLink(j,llink(j,k))
!           GeoPreventFor(llink(j,k),MVPF) = 0 ! allowed
	GeoPreventFor(j,k)=0 ! allowed
        MVPB=MoveNoBackLink(j,llink(j,k))
        GeoPreventBack(ForToBackLink(llink(j,k)),MVPB)=0 ! allowed
                elseif(llink(j,k).eq.mright)then
			     move(j,k)=3
! To take into account prevented movements defined in movement.dat
!           MVPF = MoveNoForLink(j,llink(j,k))
!           GeoPreventFor(llink(j,k),MVPF) = 0 ! allowed
	GeoPreventFor(j,k)=0 ! allowed
        MVPB=MoveNoBackLink(j,llink(j,k))
        GeoPreventBack(ForToBackLink(llink(j,k)),MVPB)=0 ! allowed
                elseif(llink(j,k).eq.mother1)then
			     move(j,k)=4
! To take into account prevented movements defined in movement.dat
!           MVPF = MoveNoForLink(j,llink(j,k))
!           GeoPreventFor(llink(j,k),MVPF) = 0 ! allowed
		  GeoPreventFor(j,k)=0 ! allowed
            MVPB=MoveNoBackLink(j,llink(j,k))
            GeoPreventBack(ForToBackLink(llink(j,k)),MVPB)=0 ! allowed
                elseif(llink(j,k).eq.mother2)then
			     move(j,k)=5
! To take into account prevented movements defined in movement.dat
!           MVPF = MoveNoForLink(j,llink(j,k))
!           GeoPreventFor(llink(j,k),MVPF) = 0 ! allowed
	GeoPreventFor(j,k)=0 ! allowed
        MVPB=MoveNoBackLink(j,llink(j,k))
        GeoPreventBack(ForToBackLink(llink(j,k)),MVPB)=0 ! allowed
!                elseif(llink(j,k).eq.muturn) then
!			     move(j,k)=6
      elseif(llink(j,k).eq.muturn.and.UturnFlag(j).eq.1)then
			     move(j,k)=6
! To take into account prevented movements defined in movement.dat
!           MVPF = MoveNoForLink(j,llink(j,k))
!           GeoPreventFor(llink(j,k),MVPF) = 0 ! allowed
	GeoPreventFor(j,k)=0 ! allowed
        MVPB=MoveNoBackLink(j,llink(j,k))
        GeoPreventBack(ForToBackLink(llink(j,k)),MVPB)=0 ! allowed
	          elseif(llink(j,k).eq.mother3)then
		move(j,k)=7
! To take into account prevented movements defined in movement.dat
!           MVPF = MoveNoForLink(j,llink(j,k))
!           GeoPreventFor(llink(j,k),MVPF) = 0 ! allowed
	GeoPreventFor(j,k)=0 ! allowed
        MVPB=MoveNoBackLink(j,llink(j,k))
        GeoPreventBack(ForToBackLink(llink(j,k)),MVPB)=0 ! allowed
	          elseif(llink(j,k).eq.mother4)then
			     move(j,k)=8
! To take into account prevented movements defined in movement.dat
!           MVPF = MoveNoForLink(j,llink(j,k))
!           GeoPreventFor(llink(j,k),MVPF) = 0 ! allowed
		  GeoPreventFor(j,k) = 0 ! allowed
            MVPB=MoveNoBackLink(j,llink(j,k))
            GeoPreventBack(ForToBackLink(llink(j,k)),MVPB)=0 ! allowed
			  endif
c --  based on the setting in movement.dat, if a movement is prohibited, 
c --  update the GeopreventFor(forward*)
             enddo
c --
            if(mleft.gt.0)then
             j=mleft
              do k=1,inlink(j,nu_mv+1)
                if(inlink(j,k).eq.mlink)then
                  movein(j,k)=1
	            exit
                endif
              end do
            endif
c --
            if(mst.gt.0)then
              j=mst
              do k=1,inlink(j,nu_mv+1)
                if(inlink(j,k).eq.mlink)then
                   movein(j,k)=2
	             exit
                endif
              end do
            endif
c --
            if(mright.gt.0)then    
              j=mright
              do k=1,inlink(j,nu_mv+1)
                if(inlink(j,k).eq.mlink)then
                   movein(j,k)=3
                   exit
                endif
              end do
           endif
c --
           if(mother1.gt.0)then
              j=mother1
              do k=1,inlink(j,nu_mv+1)
                if(inlink(j,k).eq.mlink)then
                  movein(j,k)=4
                  exit
                endif
              enddo
           endif
c --
           if(mother2.gt.0)then
              j=mother2
              do k=1,inlink(j,nu_mv+1)
                if(inlink(j,k).eq.mlink)then
                  movein(j,k)=5
                  exit
                endif
              enddo
           endif
c --
            if(muturn.gt.0)then
              j=muturn
              do k=1,inlink(j,nu_mv+1)
                if(inlink(j,k).eq.mlink)then
                  movein(j,k)=6
                  exit
                endif
              end do
            endif
c --
           if(mother3.gt.0)then
              j=mother3
              do k=1,inlink(j,nu_mv+1)
                if(inlink(j,k).eq.mlink)then
                  movein(j,k)=7
                  exit
                endif
              enddo
           endif
c --
           if(mother4.gt.0)then
              j=mother4
              do k=1,inlink(j,nu_mv+1)
                if(inlink(j,k).eq.mlink)then
                  movein(j,k)=8
                  exit
                endif
              enddo
           endif
c --
100   continue
c	
c	print *, 'Alex291',nzones,nubus
c	
      	do i=1,noofarcs
	 if(link_iden(i).eq.100)then ! only for origin connectors
	  do j=1,llink(i,nu_mv+1)
          move(i,j)=2 ! Through
          enddo
	 endif
	enddo
c --
c -- end read movement data
c -- start read the left-turn capacity
c --  
c       if(EOF(48)) then
c	  ErString = "leftcap.dat"
c	  call ErReadEOF(ErString)
c	 endif 
      read(48,*,iostat=error)
      do 400 k=1,5
      read(48,311,iostat=error) fgcratio
c	print 311,fgcratio
311   format(4x,f3.1)
c	pause
      if(fgcratio.eq.0.3) igc=1
      if(fgcratio.eq.0.4) igc=2
      if(fgcratio.eq.0.5) igc=3
      if(fgcratio.eq.0.6) igc=4
      if(fgcratio.eq.0.7) igc=5
      do i=1,3
      read(48,262,iostat=error) itmp,(leftcapWb(igc,itmp,j),j=1,7)
c	print 262,itmp,(leftcapWb(igc,itmp,j),j=1,7)
262   format(i1,3x,7i5)
c	pause
      enddo
400   continue
      read(48,*,iostat=error)
      do i=1,5
      read(48,311,iostat=error) fgcratio
c	print 311,fgcratio
c	pause
      if(fgcratio.eq.0.3) igc=1
      if(fgcratio.eq.0.4) igc=2
      if(fgcratio.eq.0.5) igc=3
      if(fgcratio.eq.0.6) igc=4
      if(fgcratio.eq.0.7) igc=5
	irows=ifix((fgcratio+0.001)*10)*3
	do k=1,irows
	read(48,313,iostat=error)ivolume,itmp,
     +(leftcapWOb(igc,itmp,ivolume,j),j=1,7)
c	 print 313,ivolume,itmp,(leftcapWOb(igc,itmp,ivolume,j),j=1,7)
c	 pause
	enddo
c Set the default values for iivolume> ivolume
	do iivolume=ivolume+1,7
	do iu=1,3
      leftcapWOb(igc,iu,iivolume,:)=leftcapWOb(igc,iu,ivolume,:) 
	enddo
	enddo
313    format(i1,i4,7i5)
      enddo
c	print *, 'Alex291b',nzones,nubus
c	nzones=alexnzones
c --
c -- end of read left turn capacity
c --
c -- start read 4 way stop sign capacity
      do i=1,NLevel
C       if(EOF(56)) then
C	  ErString = "StopCap4Way.dat"
C	  call ErReadEOF(ErString)
C	 endif
      read(56,*,iostat=error) (stopcap4w(i,j),j=1,NMove)
      enddo
c --  end of reading 4 way stop sign capacity
c
c -- start read 2 way stop sign capacity
c	
      do i=1,Level2N
C       if(EOF(57)) then
C	  ErString = "StopCap2Way.dat"
C	  call ErReadEOF(ErString)
C	 endif
      read(57,*,iostat=error) stopcap2wIND(i),
     *(stopcap2w(i,j),j=1,Move2N)
      enddo 
c --  end of reading 2 way stop sign capacity
c	
c	  print *, 'Alex2912',nzones,nubus
c -- start read Yield Sign capacity
c	
      do i=1,Level2N
C       if(EOF(60)) then
C	  ErString = "YieldCap.dat"
C	  call ErReadEOF(ErString)
C	 endif
       read(60,*,iostat=error) YieldCapIND(i),(YieldCap(i,j),j=1,Move2N)
      enddo
c --
c --  end of reading 2 way stop sign capacity
c --
c -- read the vms data
c --
c -- vms_num : number of vms
c --
c -- i1 and i2 are the upstream and downstream nodes for the link
c -- on which the VMS exists.
c --
c    	print *, 'Alex2913',nzones,nubus
      if(vms_num.gt.0)then    
c	
	  do i=1,vms_num
      read(49,*,iostat=error) vmstype(i),i1,i2,vms(i,2),vms(i,3),
     + vms_start(i),vms_end(i)
c     read subpath for type 2
      if(vmstype(i).eq.2)then
	  read(49,*,iostat=error) (vmstypetwopath(i,k)%node,k=1,vms(i,3))      
        if(vmstypetwopath(i,1)%node.ne.i2)then
         write(911,*) 'error in',i,'th  VMS'
         write(911,*) 'error in Type 2 VMS subpath specification'
         stop
	  endif
        vms(i,2)=100.0
        do mmp=1,vms(i,3)-1
          vmstypetwopath(i,mmp)%link=
     *    GetFLinkFromNode(idnum(vmstypetwopath(i,mmp)%node),
     *                   idnum(vmstypetwopath(i,mmp+1)%node))
        enddo
      endif  
c	
c	  print *, 'Alex2914',nzones
c --  the kth path specified in vms.dat for type 3 vms
c --  needs to be smaller or equal to the kay as specified in network.dat
	  if(vmstype(i).eq.3)then
	  if(vms(i,2).gt.100.or.vms(i,2).lt.0)then
	   write(911,*) "Error in vms.dat type 3"
	   write(911,*) "Check vms(i,2) for response percentage",i
	   stop
	  endif
	  if(vms(i,3).ne.0.and.vms(i,3).ne.1)then
	   write(911,*) "Error in vms.dat type 3"
         write(911,*) "Diversion Mode shoule be either 1 or 0"
	   stop
	  endif
	  endif
      vms(i,1)=GetFLinkFromNode(idnum(i1),idnum(i2))
      if(vms(i,1).eq.0)then 
         write(911,*) 'INPUT ERROR : VMS data file'
         write(911,*) 'check the VMS link' 
         write(911,*) 'for VMS number',i
         stop
      endif
c --
      enddo   
c	
	endif ! vms_num.gt.0
c
c --
c --  end of reading VMS data
c --
c
c -- read bus data
c --
c --nubus : number of buses in the network.
c -- i1 and i2 are the upstream and downstream nodes for the starting link.
c --
c -- in this section, we read the bus attributes and path one by one
c -- and insert them into BusAtt_Array by calling BusAtt_Insert subroutine
c	
c	print *, 'Alex292',nzones,nubus
c	
      if(nubus.gt.0)then
	  tlatest_bus=0.0
        do i=1,nubus
      read(50,*,iostat=error) i1,i2,busstart(i),busdwell(i),NoBusNode(i)
c     print *, 'Alex2',NoBusNode(i)
          read(50,*,iostat=error) (buspathtmp(k),k=1,NoBusNode(i))
          read(50,*,iostat=error) (busstoptmp(k),k=1,NoBusNode(i))
c	print *,'Alex21',i
c    	print *, 'Alex21',nzones,i,NoBusNode(i)
          do kk=1,NoBusNode(i)
!            call BusAtt_Insert(i,kk,1,idnumbuspathtmp(kk))
c    	print *, 'Alex22',nzones
	    internalnodenumber=idnum(buspathtmp(kk))
            if(internalnodenumber.eq.0)then 
          write(911,*) 'INPUT ERROR : bus data file'
          write(911,*) 'node',buspathtmp(kk), ' doesnot exist'
          write(911,*) 'for bus number',i
            stop
            endif
	call BusAtt_Insert(i,kk,1,internalnodenumber)
        call BusAtt_Insert(i,kk,2,busstoptmp(kk))
	  enddo
	  do kk=2,NoBusNode(i)
	LinkNo=GetFLinkFromNode(idnum(buspathtmp(kk-1)),
     +idnum(buspathtmp(kk)))
c	
	    if(LinkNo.eq.0)then
          write(911,*) 'INPUT ERROR : bus data file'
          write(911,*) 'link ',buspathtmp(kk-1), '->',buspathtmp(kk),
     +	 ' doesnot exist'
          write(911,*) ' for bus number',i
            stop
	    endif
	 enddo
c	
	iflag1=0
	ifinalnode=buspathtmp(NoBusNode(i))
	iflag1=iConZone(idnum(ifinalnode),1)
       if(iflag1.eq.0)then 
          write(911,*) 'INPUT ERROR : bus data file'
          write(911,*) 'final node ',ifinalnode, 'for bus number',i,
     + ' is not a destination node'
          stop
       endif
c*************************************************
c          itmp=destination(MasterDest
c     +         (izone(buspathtmp(NoBusNode(i)))))
c************************************************
c          itmp=destination(MasterDest
c     +         (izone(idnum(buspathtmp(NoBusNode(i))))))
c We only need to know the centriod number
      itmp=destination(MasterDest(iConZone(idnum(ifinalnode),2)))
c*************************************************   
c    	print *, 'Alex293',nzones
c	
	Index1D=NoBusNode(i)+1
          call BusAtt_Insert(i,Index1D,1,itmp)
          call BusAtt_Insert(i,Index1D,2,0)
c	
          if(busstart(i).gt.tlatest_bus) tlatest_bus=busstart(i)
          do j=1,noofarcs
            if(iunod(j).eq.idnum(i1).and.idnod(j).eq.idnum(i2))then
               buslink(i)=j !G
	         exit
	      endif
          enddo
c    	print *, 'Alex2931',nzones 
c --
c -- Check for input errors
c --
c    	print *, 'Alex2931b',nzones ,i,buslink(i)
         if(buslink(i).eq.0)then 
          write(911,*) 'INPUT ERROR : bus data file'
          write(911,*) 'check the starting link' 
          write(911,*) 'for bus number',i
          stop
         endif
        enddo ! end of read bus loop 
	 endif
c --
c -- end of reading bus data
c --
c    	print *, 'Alex293a',nzones 
c --
c -- read incident data
c --
c -- inici_num : number of incidents
c -- 
c -- i1 and i2 are the upstream and downstream nodes for the link on which
c -- the incident occures.
c --
c --
      if(inci_num.gt.0)then
        do i=1,inci_num
         read(46,*) i1,i2,inci(i,1),inci(i,2),inci(i,3)
         do k=1,noofarcs
          if(iunod(k).eq.idnum(i1).and.idnod(k).eq.idnum(i2)) incil(i)=k !G
         enddo
c --
c -- Check for input errors
c --
         if(incil(i).eq.0)then 
          write(911,*) 'INPUT ERROR : incident data file'
          write(911,*) 'check the incident link' 
          write(911,*) 'for incident number',i
          stop
         endif
       enddo
      endif
c --
c -- determine the opposing link and its number of lanes for all links.
c --
c --
c    	print *, 'Alex293b',nzones 
c	
      do i=1,noofarcs
        do j=1,llink(i,nu_mv+1)
           if(move(i,j).eq.2)then
              il=llink(i,j)
             do ii=1,noofarcs
               if(idnod(il).eq.iunod(ii).and.
     +            iunod(il).eq.idnod(ii))then
                  ill=ii
	            exit
               endif
             end do
	        if(ill.gt.0)then
                opp_linkP(i)=ill
                opp_lane(i)=nlanes(ill)
	        endif
           endif
        enddo  
      enddo
c --
c --  start reading TraffFlowModel.dat
c --
      do i=1,NoOfFlowModel
       read(55,*) MG, FlowModelType(i)
	 if(FlowModelType(i).gt.2.or.FlowModelType(i).lt.1)then
	  write(911,*) "Error in Traffic Flow Model Type"
	  write(911,*) "Currenlty, only two types are supported"  
	  write(911,*) "Please see user's manual for details"
	  stop
	 endif
c	
	 Select Case (FlowModelType(i))
	  Case (1)
	    read(55,*) MGreenS(i)%Kcut, MGreenS(i)%Vf2,MGreenS(i)%V02,
     *            MGreenS(i)%Kjam2,MGreenS(i)%alpha2
	  Case (2)
	    read(55,*) MT1,MT2,MGreenS(i)%V02,
     *               MGreenS(i)%Kjam2,MGreenS(i)%alpha2
          MGreenS(i)%Kcut=0	    
	 End Select 
	enddo
c --  assign flow model to connectors, this default model is to make vehicle take infimisial time to centroid
      	FlowModelType(NoOfFlowModel+1)=1
      	MGreenS(NoOfFlowModel+1)%Kcut=300
        MGreenS(NoOfFlowModel+1)%Vf2=100
        MGreenS(NoOfFlowModel+1)%V02=100
        MGreenS(NoOfFlowModel+1)%Kjam2=300
        MGreenS(NoOfFlowModel+1)%alpha2=1	      
c --
c -- Set the initial values for the link performance (speed, density, ...) 
c --
c    	print *, 'Alex293d',nzones 
c	
      do 76 i=1,noofarcs
         xl(i)=nlanes(i)*s(I)
         original_xl(i)=xl(i)
         v(i)=(SpeedLimit(i)+Vfadjust(i))/60.0
         vtmp(i)=(SpeedLimit(i)+Vfadjust(i))/60.0		 
         statmpt(i)=s(i)/v(i)
         TTimeOfBackLink(ForToBackLink(i))=statmpt(i)
         IH=FlowModelnum(i)
         cmax(i)=MGreenS(IH)%Kjam2
76    continue
c
c	print *, 'Alex294',nzones
c	
       call read_signals()
c		print *, 'Alex294a',nzones
c --
c --   read the pricing scenario
c --
          read(51,*)
     +    price_regular_c,price_hot_lov_c,
     +    price_hot_hov_c,time_value 
c -- convert the cost into time values
c
C       price_regular = price_regular_c / time_value  
C       price_hot_lov = price_hot_lov_c / time_value  
C       price_hot_hov = price_hot_hov_c / time_value  
c	
       price_regular=price_regular_c*60/time_value  
       price_hot_lov=price_hot_lov_c*60/time_value  
       price_hot_hov=price_hot_hov_c*60/time_value  
c --
c --   end reading the pricing scenario         
c --
c	print *, 'Alex295',nzones

!********************************************************************
!********************************************************************
c --  Starting Reading origin.dat
! --  NoofGenLinksPerZone is read from origin.dat:izlins
! --  LinkNoInZone() keeps track of the link number:izone
! --  total link length for zones are stored in TotalLinkLenPerZone():totlmz
c	print *,'Alex0b',nzones
      do i=1,nzones
	SumLoadWeight=0.0
	read(52,*,iostat=error) izonetmp,NoofGenLinksPerZone(i),IDGen
c	print *,'Alex0a',izonetmp,NoofGenLinksPerZone(i),IDGen
	If(IDGen.gt.0) LoadWeightID(i)=.True.
	if(error.ne.0)then
         write(911,*) 'Error when reading origin.dat 10',
     +   izonetmp,NoofGenLinksPerZone(i),IDGen
	   stop
	endif
!	if(NoofGenLinksPerZone(i).eq.0) then
!         write(911,*) 'Error when reading origin.dat'
!         write(911,*) 'Each zone needs to have at least one gen link'
!         write(911,*) 'Please check zone', i
!	   stop
!	endif
c	
	 do j = 1, NoofGenLinksPerZone(i)
         read(52,*,iostat=error) IUpNode,IDnNode, LWTmp !LWTmp is a temp var for LWTmp
c	
	   if(error.ne.0) then
           write(911,*) 'Error when reading origin.dat 11'
	     stop
	   endif
c	
	   if(izone(idnum(IUpNode)).ne.i.and.izone(idnum(IDnNode)).ne.i)
     *                                                            then
         INQUIRE(UNIT = 511, OPENED = Fexist)
	   if(.not. Fexist) then
	 open(file='Warning.dat',unit=511,status='unknown',iostat=error)
	    if(error.ne.0) then
            write(911,*) 'Error when opening Warning.dat'
	      stop
	    endif
         endif
c	
         write(511,'("Link",i7,"  -->",i7," receives demand from zone",
     *     i6," not a physical zone for both nodes")')IUpNode,IDnNode,i
         endif
	   LinkNo=GetFLinkFromNode(idnum(IUpNode),idnum(IDnNode))
! Remark a boundary freeway link can be a generation link
	   if(link_iden(LinkNo).eq.1) then
           write(511,'("Error in origin.dat")')
	     write(511,'("link ",i5," -->",i5," is highway/freeway")') 
     *                   IUpNode,IDnNode
	     write(511,'("It cannt be a generation link in zone",i3)') i 
!	     stop
	   endif
	   if(LinkNo.lt.1)then
	      write(911,*) 'Error in origin.dat 12'
            write(911,*) 'Link doesnt exit'
            write(911,*) 'zone, ud, nd',i,IUpNode,IDnNode
	      stop 
	   endif
	LinkNoInZone(i,j)=LinkNo
c --	print *,'Alex4',LinkNoInZone(i,j)
	   if(LoadWeightID(i))then !User-specified Loading weight is used
           SumLoadWeight=SumLoadWeight+LWTmp
	     LoadWeight(LinkNo)=LWTmp
	     TotalLinkLenPerZone(i)=TotalLinkLenPerZone(i)+
     *                            LoadWeight(LinkNo)
         else
	     TotalLinkLenPerZone(i)=TotalLinkLenPerZone(i)+xl(LinkNo)
	   endif
	 enddo
	   if(LoadWeightID(i))then
          if(abs(SumLoadWeight-1.0).gt.0.0001)then
	     write(911,*) 'Error in origin.dat 13'
	     write(911,*) 'The sum of loading weights in zone',i,
     *                  'is not 1.0'
           stop
	    endif	 
	   endif
	enddo
c	print *, 'Alex296',nzones    
c --  updates the iGenZone: which super zone that link i receives demand from
      do i=1,noofarcs
        do j=1,nzones
	    do k=1,NoofGenLinksPerZone(j)
            if(i.eq.LinkNoInZone(j,k))then
              iGenZone(i,1)=iGenZone(i,1)+1
	        iGenZone(i,iGenZone(i,1)+1)=j !iGenZone should keep the original zone number
	      endif
	    enddo
	  enddo
	enddo
c --  Check if iGenZone is correct
      do i=1,noofarcs
	if(iGenZone(i,1).gt.0.and.idnod(i).gt.noofnodes_org)then
         write(911,*) 'errors: iGenZone contains connectors'
      endif
	enddo
!********************************************************************
c --
c --  Read the optional output information
c -- 
      read(101,*) i30,i30_t
      read(101,*) i31,i31_t
      read(101,*) i32,i32_t
      read(101,*) i33,i33_t
      read(101,*) i34,i34_t
      read(101,*) i35,i35_t
      read(101,*) i36,i36_t
      read(101,*) i37,i37_t
      read(101,*) i38,i38_t
      read(101,*) i39,i39_t
	read(101,*) idemand_info
!      read(101,*) i40,i40_t
      i40=1
	i40_t=10 ! hard-wire them for now
	i18=1 !Fix i18 = 1 for now since we need to output vehicle trajectory as the default
	if(i30.gt.0) open(file='OutLinkGen.dat',unit=30,status='unknown')
	if(i31.gt.0) open(file='OutLinkVeh.dat',unit=31,status='unknown')
	if(i32.gt.0) open(file='OutLinkQue.dat',unit=32,status='unknown')
        if(i33.gt.0) open(file='OutLinkSpeedAll.dat',unit=33,status=
     +  'unknown')
	if(i34.gt.0) open(file='OutLinkDent.dat',unit=34,status=
     +  'unknown')
        if(i35.gt.0) open(file='OutLinkSpeedFree.dat',unit=35,status=
     +  'unknown')
        if(i36.gt.0) open(file='OutLinkDentFree.dat',unit=36,status=
     +  'unknown')
      if(i37.gt.0) open(file='OutLeftFlow.dat',unit=37,status='unknown')
	if(i38.gt.0) open(file='OutGreen.dat',unit=38,status='unknown')
	if(i39.gt.0) open(file='OutFlow.dat',unit=39,status='unknown')
      if(i40.gt.0) open(file='OutAccuVol.dat',unit=40,status='unknown')
	open(file='LinkVolume.dat',unit=29,status='unknown')
! -- start reading Work Zone data
      if(WorkZoneNum.gt.0)then
      do i=1,WorkZoneNum
        read(58,*) FNodetmp,TNodetmp,WorkZone(i)%ST,
     * WorkZone(i)%ET,WorkZone(i)%CapRed,
     * WorkZone(i)%SpeedLmt,WorkZone(i)%Discharge
       WorkZone(i)%FNode=idnum(FNodeTmp)
       WorkZone(i)%TNode=idnum(TNodetmp)
       enddo
	endif
!work zone and an incident at the same time
	   k=0
	   if(WorkZoneNum.gt.0.and.inci_num.gt.0)then
		do i=1,inci_num
			do j=1,WorkZoneNum
			if(iunod(incil(i)).eq.WorkZone(j)%FNode.and.
     *			idnod(incil(i)).eq.WorkZone(j)%TNode)then
				k=incil(i)
	  write(511,*)
	  write(511,*)'Link',nodenum(iunod(k)),'   ->',nodenum(idnod(k))
	  write(511,*)'Has a work zone and an incident specified'
	  write(511,*)'simultaneously. The work zone will override the' 
	  write(511,*)'incident when both are active'
	  write(511,*)
			endif
			enddo
		enddo
	  endif

c -- how many simulation interval  do we average the travel time 
c -- for the time dependant KSP.
      interval_avg_for_tdksp=ftr
      timeinterval=interval_avg_for_tdksp*tii
!--  check warning.dat's file size
c	
c	print *,'Alex1000'
c	Alex: cancle warning message . . .
c      if(iteration.eq.0)then
c --	
c      INQUIRE(UNIT=511,OPENED=Fexist)
c     IF(Fexist)THEN
c      write(6,'("There are warning messages recorded in warning.dat")') 
c      write(6,'("")') 
c      write(6,'("Type <Y> or <y> followed by <enter> to exit program")')
c 	  write(6,'("Open the warning.dat file to see warning messages")') 
c	  write(6,'("Otherwise, type any other key followed by <enter>")') 
c	  write(6,'("to continue executing the program")') 
c	  write(6,'("")') 		 
c	  read(*,*) Reply
c      if(iachar(reply).eq.89.or.iachar(reply).eq.121)then ! Y or y
c	    stop
c	endif
c --	IP=system("cls")
c      ENDIF
c	
c      endif
c	

       deallocate(demtmp)
	
      if(realdm.ne.1)then
c        print *,'Alex1100',MaxVehicles,noofarcs,noofarcs_org
c        if(iteration.eq.0) pause
       if(.not.allocated(linktraveltime))then
        allocate(linktraveltime(MaxVehicles,noofarcs),stat=error)
        if(error.ne.0)then
        write(911,*)"allocate linktraveltime error-insuffi memory"
        print *, 'allocate linktraveltime error-insuffi memory'
        stop
        endif		
       endif
          linktraveltime(:,:)=0	   
      endif

      return 
      end
